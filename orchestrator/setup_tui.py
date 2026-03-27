"""OpenClaw-style interactive setup wizard for Project Orchestrator configuration."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol

from InquirerPy.base.control import Choice as InquirerChoice
from InquirerPy.base.control import InquirerPyUIListControl
from InquirerPy.containers.message import MessageWindow
from InquirerPy.containers.validation import ValidationFloat
from InquirerPy.base.complex import FakeDocument
from InquirerPy.prompts.checkbox import CheckboxPrompt
from InquirerPy.prompts.confirm import ConfirmPrompt
from InquirerPy.prompts.input import InputPrompt
from InquirerPy.prompts.list import ListPrompt
from InquirerPy.separator import Separator
from InquirerPy.utils import get_style
from prompt_toolkit.application import Application
from prompt_toolkit.filters.cli import IsDone
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import FormattedText, to_formatted_text
from prompt_toolkit.layout.containers import ConditionalContainer, FloatContainer, HSplit, Window
from prompt_toolkit.layout.controls import DummyControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.validation import ValidationError
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets.base import Frame

from orchestrator import BLOCKED_DIRS
from orchestrator.post_setup import launch_post_setup_runtime
from orchestrator.setup_support import (
    EnvironmentReport,
    SetupSummary,
    WorkspaceCandidate,
    WorkspaceOrchestratorCandidate,
    bootstrap_project_dependencies,
    candidates_from_config,
    classify_current_folder,
    detect_environment,
    environment_summary,
    final_instruction_text,
    load_setup_config,
    render_orchestrator_config,
    resolve_setup_input_path,
    suggested_workspace_orchestrator_candidates_for_root,
    suggested_workspace_candidates_for_root,
    validate_setup_target_path,
    workspace_candidates_for_orchestrator,
    write_setup_files,
)

RUNTIME_VALUES = ("claude", "cursor", "codex", "opencode")
MODE_VALUES = ("local", "remote")
REMOTE_ENV_VALUES = ("local", "ssh", "kubernetes")
SETUP_BLOCKED_PATH_NAMES = BLOCKED_DIRS | {"skills", "templates", "scripts", "bridge", ".venv"}
CHANNEL_STATES = {
    "none": (False, False),
    "slack": (True, False),
    "telegram": (False, True),
    "both": (True, True),
}
WIZARD_BACK_RESULT = "__wizard_back__"
WIZARD_STYLE = get_style(
    {
        "question": "bold",
        "answered_question": "bold",
        "pointer": "#4aa8ff bold",
        "marker": "#4aa8ff",
        "checkbox": "#4aa8ff",
        "answer": "#4aa8ff",
        "instruction": "#8b949e",
        "long_instruction": "#8b949e",
        "choice-primary": "",
        "choice-primary-highlighted": "#4aa8ff bold",
        "choice-primary-hover": "bold",
        "choice-primary-highlighted-hover": "#4aa8ff bold",
        "choice-secondary": "#8b949e",
        "separator": "#8b949e italic",
    },
    style_override=False,
)
WIZARD_PROMPT_STYLE = Style.from_dict(WIZARD_STYLE.dict)

StepResult = Literal["next", "back", "stay", "cancel", "success"]
RenderableText = str | list[tuple[str, str]] | FormattedText
WIZARD_CANCEL_RESULT = "__wizard_cancel__"


@dataclass(slots=True)
class WizardOption:
    value: str
    label: str
    hint: str = ""
    highlight: bool = False


@dataclass
class StyledChoice(InquirerChoice):
    primary: str | None = None
    secondary: str | None = None
    highlighted: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.primary is None:
            self.primary = self.name


class WizardCancelledError(RuntimeError):
    """Raised when the interactive wizard is cancelled by the user."""


class WizardBackError(RuntimeError):
    """Raised when the user wants to go back to the previous screen."""


def build_instruction_fragments(
    *,
    body: list[tuple[str, str]],
) -> FormattedText:
    divider = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    return FormattedText([("class:choice-secondary", f"{divider}\n"), *body])


def select_instruction_fragments() -> FormattedText:
    return build_instruction_fragments(
        body=[
            ("class:choice-secondary", "Use the "),
            ("class:choice-primary-highlighted", "[arrow keys]"),
            ("class:choice-secondary", ", then press "),
            ("class:choice-primary-highlighted", "[Enter]"),
            ("class:choice-secondary", ", "),
            ("class:choice-primary-highlighted", "[Esc]"),
            ("class:choice-secondary", " goes back. "),
            ("class:choice-primary-highlighted", "[Ctrl+Z]"),
            ("class:choice-secondary", " exits immediately."),
        ]
    )


def multiselect_instruction_fragments() -> FormattedText:
    return build_instruction_fragments(
        body=[
            ("class:choice-secondary", "Use "),
            ("class:choice-primary-highlighted", "[Space]"),
            ("class:choice-secondary", " to toggle, "),
            ("class:choice-primary-highlighted", "[arrow keys]"),
            ("class:choice-secondary", " to move, then press "),
            ("class:choice-primary-highlighted", "[Enter]"),
            ("class:choice-secondary", ". "),
            ("class:choice-primary-highlighted", "[Esc]"),
            ("class:choice-secondary", " goes back. "),
            ("class:choice-primary-highlighted", "[Ctrl+Z]"),
            ("class:choice-secondary", " exits immediately."),
        ]
    )


def text_instruction_fragments() -> FormattedText:
    return build_instruction_fragments(
        body=[
            ("class:choice-secondary", "Press "),
            ("class:choice-primary-highlighted", "[Enter]"),
            ("class:choice-secondary", " to submit. Leave empty to accept the default. "),
            ("class:choice-primary-highlighted", "[Esc]"),
            ("class:choice-secondary", " goes back. "),
            ("class:choice-primary-highlighted", "[Ctrl+Z]"),
            ("class:choice-secondary", " exits immediately."),
        ]
    )


def confirm_instruction_fragments() -> FormattedText:
    return build_instruction_fragments(
        body=[
            ("class:choice-secondary", "Press "),
            ("class:choice-primary-highlighted", "[y]"),
            ("class:choice-secondary", " or "),
            ("class:choice-primary-highlighted", "[n]"),
            ("class:choice-secondary", ", then "),
            ("class:choice-primary-highlighted", "[Enter]"),
            ("class:choice-secondary", ". "),
            ("class:choice-primary-highlighted", "[Esc]"),
            ("class:choice-secondary", " goes back. "),
            ("class:choice-primary-highlighted", "[Ctrl+Z]"),
            ("class:choice-secondary", " exits immediately."),
        ]
    )


class WizardPrompter(Protocol):
    """Prompt adapter for the setup wizard."""

    def clear_screen(self) -> None: ...

    def intro(self, title: str) -> None: ...

    def note(self, message: RenderableText, title: str | None = None) -> None: ...

    def select(
        self,
        message: str,
        options: list[WizardOption],
        default: str | None = None,
    ) -> str: ...

    def multiselect(
        self,
        message: str,
        options: list[WizardOption],
        defaults: list[str] | None = None,
    ) -> list[str]: ...

    def text(
        self,
        message: str,
        default: str = "",
        validate: Callable[[str], str | None] | None = None,
    ) -> str: ...

    def secret(
        self,
        message: str,
        default: str = "",
        validate: Callable[[str], str | None] | None = None,
    ) -> str: ...

    def confirm(self, message: str, default: bool = True) -> bool: ...

    def outro(self, message: str) -> None: ...


class StyledListControl(InquirerPyUIListControl):
    """List control that renders a highlighted primary label and dim metadata."""

    def __init__(
        self,
        choices: list[StyledChoice],
        default: str | None,
        pointer: str,
        marker: str,
        marker_pl: str,
        multiselect: bool,
    ) -> None:
        self._pointer = pointer
        self._marker = marker
        self._marker_pl = marker_pl
        super().__init__(choices=choices, default=default, multiselect=multiselect, session_result=None)

    def _primary_style(self, choice: dict[str, object], hovered: bool) -> str:
        highlighted = bool(choice.get("highlighted"))
        if highlighted and hovered:
            return "class:choice-primary-highlighted-hover"
        if highlighted:
            return "class:choice-primary-highlighted"
        if hovered:
            return "class:choice-primary-hover"
        return "class:choice-primary"

    def _append_label_tokens(
        self,
        tokens: list[tuple[str, str]],
        choice: dict[str, object],
        hovered: bool,
    ) -> None:
        if isinstance(choice["value"], Separator):
            tokens.append(("class:separator", str(choice["name"])))
            return

        tokens.append((self._primary_style(choice, hovered), str(choice.get("primary") or choice["name"])))
        secondary = str(choice.get("secondary") or "").strip()
        if secondary:
            tokens.append(("class:choice-secondary", f"  {secondary}"))

    def _get_hover_text(self, choice) -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = [("class:pointer", self._pointer)]
        if self._marker or self._marker_pl:
            tokens.append(("class:marker", self._marker if choice["enabled"] else self._marker_pl))
        tokens.append(("[SetCursorPosition]", ""))
        self._append_label_tokens(tokens, choice, hovered=True)
        return tokens

    def _get_normal_text(self, choice) -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = [("", len(self._pointer) * " ")]
        if self._marker or self._marker_pl:
            tokens.append(("class:marker", self._marker if choice["enabled"] else self._marker_pl))
        self._append_label_tokens(tokens, choice, hovered=False)
        return tokens


class StyledCheckboxControl(InquirerPyUIListControl):
    """Checkbox control that renders a highlighted primary label and dim metadata."""

    def __init__(
        self,
        choices: list[StyledChoice],
        default: str | None,
        pointer: str,
        enabled_symbol: str,
        disabled_symbol: str,
    ) -> None:
        self._pointer = pointer
        self._enabled_symbol = enabled_symbol
        self._disabled_symbol = disabled_symbol
        super().__init__(choices=choices, default=default, multiselect=True, session_result=None)

    def _primary_style(self, choice: dict[str, object], hovered: bool) -> str:
        highlighted = bool(choice.get("highlighted"))
        if highlighted and hovered:
            return "class:choice-primary-highlighted-hover"
        if highlighted:
            return "class:choice-primary-highlighted"
        if hovered:
            return "class:choice-primary-hover"
        return "class:choice-primary"

    def _append_label_tokens(
        self,
        tokens: list[tuple[str, str]],
        choice: dict[str, object],
        hovered: bool,
    ) -> None:
        if isinstance(choice["value"], Separator):
            tokens.append(("class:separator", str(choice["name"])))
            return
        tokens.append(
            (
                "class:checkbox",
                self._enabled_symbol if choice["enabled"] else self._disabled_symbol,
            )
        )
        if self._enabled_symbol and self._disabled_symbol:
            tokens.append(("", " "))
        tokens.append((self._primary_style(choice, hovered), str(choice.get("primary") or choice["name"])))
        secondary = str(choice.get("secondary") or "").strip()
        if secondary:
            tokens.append(("class:choice-secondary", f"  {secondary}"))

    def _get_hover_text(self, choice) -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = [("class:pointer", self._pointer)]
        if self._pointer:
            tokens.append(("", " "))
        tokens.append(("[SetCursorPosition]", ""))
        self._append_label_tokens(tokens, choice, hovered=True)
        return tokens

    def _get_normal_text(self, choice) -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = [("", len(self._pointer) * " ")]
        if self._pointer:
            tokens.append(("", " "))
        self._append_label_tokens(tokens, choice, hovered=False)
        return tokens


class FormattedInstructionWindow(ConditionalContainer):
    """Instruction window that accepts formatted text."""

    def __init__(self, message: RenderableText, filter, **kwargs) -> None:
        self._message = message
        super().__init__(
            Window(
                FormattedTextControl(text=self._get_message),
                dont_extend_height=True,
                **kwargs,
            ),
            filter=filter,
        )

    def _get_message(self):
        return to_formatted_text(self._message, style="class:long_instruction")


class BackListPrompt(ListPrompt):
    """List prompt that exits with a dedicated back signal on Esc."""

    def __init__(self, *args, choices: list[StyledChoice], default: str | None, **kwargs) -> None:
        pointer = kwargs.get("pointer", ">")
        marker = kwargs.get("marker", "")
        marker_pl = kwargs.get("marker_pl", "")
        multiselect = bool(kwargs.get("multiselect", False))
        self.content_control = StyledListControl(
            choices=choices,
            default=default,
            pointer=pointer,
            marker=marker,
            marker_pl=marker_pl,
            multiselect=multiselect,
        )
        long_instruction = kwargs.pop("long_instruction", "")
        ListPrompt.__init__(
            self,
            *args,
            choices=choices,
            default=default,
            long_instruction="",
            **kwargs,
        )

        self._long_instruction = long_instruction
        main_content_window = Window(
            content=self.content_control,
            height=Dimension(
                max=self._dimmension_max_height,
                preferred=self._dimmension_height,
            ),
            dont_extend_height=True,
        )
        if self._border:
            main_content_window = Frame(main_content_window)

        self._layout = FloatContainer(
            content=HSplit(
                [
                    MessageWindow(
                        message=self._get_prompt_message_with_cursor
                        if self._show_cursor
                        else self._get_prompt_message,
                        filter=True,
                        wrap_lines=self._wrap_lines,
                        show_cursor=self._show_cursor,
                    ),
                    ConditionalContainer(main_content_window, filter=~IsDone()),
                    ConditionalContainer(
                        Window(content=DummyControl()),
                        filter=~IsDone() & self._is_displaying_long_instruction,
                    ),
                    FormattedInstructionWindow(
                        message=self._long_instruction,
                        filter=~IsDone() & self._is_displaying_long_instruction,
                        wrap_lines=self._wrap_lines,
                    ),
                ]
            ),
            floats=[
                ValidationFloat(
                    invalid_message=self._get_error_message,
                    filter=self._is_invalid & ~IsDone(),
                    wrap_lines=self._wrap_lines,
                    left=0,
                    bottom=self._validation_window_bottom_offset,
                ),
            ],
        )
        self.application = Application(
            layout=Layout(self._layout),
            style=self._style,
            key_bindings=self._kb,
            after_render=self._after_render,
        )

        @self.register_kb("escape")
        def _back(event) -> None:
            self.status["answered"] = True
            self.status["result"] = WIZARD_BACK_RESULT
            event.app.exit(result=WIZARD_BACK_RESULT)

        @self.register_kb("c-z")
        def _cancel(event) -> None:
            self.status["answered"] = True
            self.status["result"] = WIZARD_CANCEL_RESULT
            event.app.exit(result=WIZARD_CANCEL_RESULT)


class BackCheckboxPrompt(CheckboxPrompt):
    """Checkbox prompt that exits with a dedicated back signal on Esc."""

    def __init__(self, *args, choices: list[StyledChoice], default: str | None = None, **kwargs) -> None:
        pointer = kwargs.get("pointer", ">")
        enabled_symbol = kwargs.get("enabled_symbol", "x")
        disabled_symbol = kwargs.get("disabled_symbol", " ")
        self.content_control = StyledCheckboxControl(
            choices=choices,
            default=default,
            pointer=pointer,
            enabled_symbol=enabled_symbol,
            disabled_symbol=disabled_symbol,
        )
        long_instruction = kwargs.pop("long_instruction", "")
        CheckboxPrompt.__init__(
            self,
            *args,
            choices=choices,
            default=default,
            long_instruction="",
            **kwargs,
        )

        self._long_instruction = long_instruction
        main_content_window = Window(
            content=self.content_control,
            height=Dimension(
                max=self._dimmension_max_height,
                preferred=self._dimmension_height,
            ),
            dont_extend_height=True,
        )
        if self._border:
            main_content_window = Frame(main_content_window)

        self._layout = FloatContainer(
            content=HSplit(
                [
                    MessageWindow(
                        message=self._get_prompt_message_with_cursor
                        if self._show_cursor
                        else self._get_prompt_message,
                        filter=True,
                        wrap_lines=self._wrap_lines,
                        show_cursor=self._show_cursor,
                    ),
                    ConditionalContainer(main_content_window, filter=~IsDone()),
                    ConditionalContainer(
                        Window(content=DummyControl()),
                        filter=~IsDone() & self._is_displaying_long_instruction,
                    ),
                    FormattedInstructionWindow(
                        message=self._long_instruction,
                        filter=~IsDone() & self._is_displaying_long_instruction,
                        wrap_lines=self._wrap_lines,
                    ),
                ]
            ),
            floats=[
                ValidationFloat(
                    invalid_message=self._get_error_message,
                    filter=self._is_invalid & ~IsDone(),
                    wrap_lines=self._wrap_lines,
                    left=0,
                    bottom=self._validation_window_bottom_offset,
                ),
            ],
        )
        self.application = Application(
            layout=Layout(self._layout),
            style=self._style,
            key_bindings=self._kb,
            after_render=self._after_render,
        )

        @self.register_kb("escape")
        def _back(event) -> None:
            self.status["answered"] = True
            self.status["result"] = WIZARD_BACK_RESULT
            event.app.exit(result=WIZARD_BACK_RESULT)

        @self.register_kb("c-z")
        def _cancel(event) -> None:
            self.status["answered"] = True
            self.status["result"] = WIZARD_CANCEL_RESULT
            event.app.exit(result=WIZARD_CANCEL_RESULT)


class BackInputPrompt(InputPrompt):
    """Text prompt that exits with a dedicated back signal on Esc."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._session.bottom_toolbar = text_instruction_fragments()

        @self.register_kb("escape")
        def _back(event) -> None:
            self.status["answered"] = True
            self.status["result"] = WIZARD_BACK_RESULT
            event.app.exit(result=WIZARD_BACK_RESULT)

        @self.register_kb("c-z")
        def _cancel(event) -> None:
            self.status["answered"] = True
            self.status["result"] = WIZARD_CANCEL_RESULT
            event.app.exit(result=WIZARD_CANCEL_RESULT)


class BackConfirmPrompt(ConfirmPrompt):
    """Confirm prompt that exits with a dedicated back signal on Esc."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._session.bottom_toolbar = confirm_instruction_fragments()

        @self.register_kb("escape")
        def _back(event) -> None:
            self.status["answered"] = True
            self.status["result"] = WIZARD_BACK_RESULT
            event.app.exit(result=WIZARD_BACK_RESULT)

        @self.register_kb("c-z")
        def _cancel(event) -> None:
            self.status["answered"] = True
            self.status["result"] = WIZARD_CANCEL_RESULT
            event.app.exit(result=WIZARD_CANCEL_RESULT)


class InquirerWizardPrompter:
    """Interactive wizard prompter backed by InquirerPy."""

    def clear_screen(self) -> None:
        if not sys.stdout.isatty():
            return
        if os.environ.get("TERM", "").strip().lower() == "dumb":
            return
        sys.stdout.write("\033[2J\033[H\033[3J")
        sys.stdout.flush()

    def intro(self, title: str) -> None:
        print()
        print(f"🟦 {title}")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print()

    def note(self, message: RenderableText, title: str | None = None) -> None:
        if title:
            print()
            print(f"{self._section_marker(title)} [{title}]")
            print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        if isinstance(message, FormattedText):
            print_formatted_text(message, style=WIZARD_PROMPT_STYLE)
        elif isinstance(message, list):
            print_formatted_text(FormattedText(message), style=WIZARD_PROMPT_STYLE)
        else:
            print(message.rstrip())
        print()

    def _section_marker(self, title: str) -> str:
        lowered = title.strip().lower()
        if lowered in {"invalid input", "workspace validation"}:
            return "🟧"
        if lowered in {"done", "setup complete"}:
            return "🟩"
        return "🟦"

    def _render_prompt_header(self, message: str) -> None:
        print()
        print(message.rstrip())

    def _choice_objects(self, options: list[WizardOption], defaults: list[str] | None = None) -> list[StyledChoice]:
        defaults = defaults or []
        return [
            StyledChoice(
                value=option.value,
                name=option.label,
                enabled=option.value in defaults,
                primary=option.label,
                secondary=option.hint,
                highlighted=option.highlight,
            )
            for option in options
        ]

    def select(
        self,
        message: str,
        options: list[WizardOption],
        default: str | None = None,
    ) -> str:
        self._render_prompt_header(message)
        result = BackListPrompt(
            message="",
            choices=self._choice_objects(options),
            default=default,
            style=WIZARD_STYLE,
            qmark=">",
            amark=">",
            pointer=">",
            marker="",
            marker_pl="",
            long_instruction=select_instruction_fragments(),
            border=False,
            cycle=True,
            raise_keyboard_interrupt=True,
            mandatory=False,
        ).execute()
        if result is None or result == WIZARD_CANCEL_RESULT:
            raise WizardCancelledError()
        if result == WIZARD_BACK_RESULT:
            raise WizardBackError()
        return str(result)

    def multiselect(
        self,
        message: str,
        options: list[WizardOption],
        defaults: list[str] | None = None,
    ) -> list[str]:
        self._render_prompt_header(message)
        result = BackCheckboxPrompt(
            message="",
            choices=self._choice_objects(options, defaults=defaults),
            default=None,
            style=WIZARD_STYLE,
            qmark=">",
            amark=">",
            pointer=">",
            enabled_symbol="x",
            disabled_symbol=" ",
            long_instruction=multiselect_instruction_fragments(),
            border=False,
            cycle=True,
            raise_keyboard_interrupt=True,
            mandatory=False,
        ).execute()
        if result is None or result == WIZARD_CANCEL_RESULT:
            raise WizardCancelledError()
        if result == WIZARD_BACK_RESULT:
            raise WizardBackError()
        return [str(value) for value in result]

    def _run_text_prompt(
        self,
        message: str,
        default: str = "",
        validate: Callable[[str], str | None] | None = None,
        *,
        is_password: bool = False,
    ) -> str:
        current_default = default
        while True:
            self._render_prompt_header(message)
            result = BackInputPrompt(
                message="",
                default=current_default,
                style=WIZARD_STYLE,
                qmark=">",
                amark=">",
                long_instruction="",
                raise_keyboard_interrupt=True,
                mandatory=False,
                is_password=is_password,
            ).execute()
            if result is None or result == WIZARD_CANCEL_RESULT:
                raise WizardCancelledError()
            if result == WIZARD_BACK_RESULT:
                raise WizardBackError()

            value = str(result)
            error = validate(value) if validate else None
            if not error:
                return value

            self.clear_screen()
            self.intro("Project Orchestrator setup")
            self.note(error, "Invalid input")
            current_default = value or current_default

    def text(
        self,
        message: str,
        default: str = "",
        validate: Callable[[str], str | None] | None = None,
    ) -> str:
        return self._run_text_prompt(message, default, validate, is_password=False)

    def secret(
        self,
        message: str,
        default: str = "",
        validate: Callable[[str], str | None] | None = None,
    ) -> str:
        return self._run_text_prompt(message, default, validate, is_password=True)

    def confirm(self, message: str, default: bool = True) -> bool:
        self._render_prompt_header(message)
        result = BackConfirmPrompt(
            message="",
            default=default,
            style=WIZARD_STYLE,
            qmark=">",
            amark=">",
            long_instruction="",
            raise_keyboard_interrupt=True,
            mandatory=False,
        ).execute()
        if result is None or result == WIZARD_CANCEL_RESULT:
            raise WizardCancelledError()
        if result == WIZARD_BACK_RESULT:
            raise WizardBackError()
        return bool(result)

    def outro(self, message: str) -> None:
        print("[Done]")
        print(message.rstrip())
        print()


def format_folder_analysis_text(cwd: Path) -> str:
    """Render the current-folder analysis note shown at the start of setup."""
    analysis = classify_current_folder(cwd)
    alternatives = ", ".join(str(path) for path in analysis.alternative_roots) or "(none)"
    reasons = "\n".join(f"- {reason}" for reason in analysis.reasons) or "- No strong signals were found."
    descriptions = {
        "existing_po": "The current directory already looks like a Project Orchestrator root.",
        "new_po_candidate": "The current directory looks like a good Project Orchestrator root candidate.",
        "workspace_candidate": (
            "The current directory looks like a workspace. "
            "Its parent directory is the suggested Project Orchestrator root."
        ),
        "unknown": "The current directory does not strongly match a known setup pattern.",
    }
    return (
        f"{descriptions.get(analysis.kind, analysis.kind)}\n"
        f"Current directory: {analysis.cwd}\n"
        f"Suggested orchestrator path: {analysis.suggested_po_root}\n"
        f"Alternative roots: {alternatives}\n"
        "Signals:\n"
        f"{reasons}"
    )


def validate_workspace_id(value: str) -> str | None:
    """Validate a workspace identifier."""
    trimmed = value.strip()
    if not trimmed:
        return "Workspace id is required."
    if "/" in trimmed or "\\" in trimmed:
        return "Workspace id must not contain path separators."
    if trimmed in BLOCKED_DIRS:
        return f"`{trimmed}` is reserved. Choose a different workspace id."
    return None


def validate_workspace_relative_path(value: str) -> str | None:
    """Validate a workspace path relative to the orchestrator root."""
    trimmed = value.strip()
    if not trimmed:
        return "Workspace path is required."
    path = Path(trimmed)
    if path.is_absolute():
        return "Workspace path must be relative to the orchestrator path."
    parts = [part for part in path.parts if part not in {".", ""}]
    if parts and parts[0] in SETUP_BLOCKED_PATH_NAMES:
        return "Workspace path must not point at an internal support directory."
    return None


def validate_workspace_orchestrator_relative_path(value: str) -> str | None:
    """Validate a Workspace Orchestrator path relative to the PO root."""
    trimmed = value.strip()
    if not trimmed:
        return "Workspace Orchestrator path is required."
    path = Path(trimmed)
    if path.is_absolute():
        return "Workspace Orchestrator path must be relative to the orchestrator path."
    parts = [part for part in path.parts if part not in {".", ""}]
    if parts and parts[0] in SETUP_BLOCKED_PATH_NAMES:
        return "Workspace Orchestrator path must not point at an internal support directory."
    return None


def validate_non_empty(value: str, label: str) -> str | None:
    """Validate that a text field is not empty."""
    if not value.strip():
        return f"{label} is required."
    return None


def validate_port_text(value: str) -> str | None:
    """Validate a TCP port field."""
    trimmed = value.strip()
    if not trimmed:
        return "Listener port is required."
    try:
        port = int(trimmed)
    except ValueError:
        return "Listener port must be a number."
    if port < 1 or port > 65535:
        return "Listener port must be between 1 and 65535."
    return None


def validate_workspace_candidates(candidates: list[WorkspaceCandidate]) -> list[str]:
    """Validate the selected workspace registry before writing setup files."""
    errors: list[str] = []
    seen_ids: set[str] = set()

    for candidate in candidates:
        if not candidate.selected:
            continue

        id_error = validate_workspace_id(candidate.workspace_id)
        if id_error:
            errors.append(id_error)
        if candidate.workspace_id in seen_ids:
            errors.append(f"Duplicate workspace id: {candidate.workspace_id}")
        seen_ids.add(candidate.workspace_id)

        path_error = validate_workspace_relative_path(candidate.relative_path)
        if path_error:
            errors.append(f"{candidate.workspace_id or 'workspace'}: {path_error}")
        if candidate.runtime not in RUNTIME_VALUES:
            errors.append(f"{candidate.workspace_id or 'workspace'}: invalid runtime `{candidate.runtime}`.")
        if candidate.mode not in MODE_VALUES:
            errors.append(f"{candidate.workspace_id or 'workspace'}: invalid mode `{candidate.mode}`.")

    return errors


class SetupWizard:
    """Stateful, prompt-driven Project Orchestrator setup wizard."""

    TOTAL_STEPS = 11

    def __init__(
        self,
        cwd: Path | None = None,
        prompter: WizardPrompter | None = None,
        environment: EnvironmentReport | None = None,
    ) -> None:
        self.cwd = (cwd or Path.cwd()).resolve()
        self.prompter = prompter or InquirerWizardPrompter()
        self.environment = environment or detect_environment(self.cwd)
        self.analysis = classify_current_folder(self.cwd)
        self.po_root = self.analysis.suggested_po_root.resolve()
        self.archive_path = (self.po_root / "ARCHIVE").resolve()
        self.archive_path_is_manual = False
        self.code_agent = "claude"
        self.default_runtime = "claude"
        self.executor_runtime = "claude"
        self.slack_enabled = False
        self.telegram_enabled = False
        self.slack_credentials: dict[str, str] = {}
        self.telegram_credentials: dict[str, str] = {}
        self.workspace_orchestrator_candidates = self._resolve_workspace_orchestrator_candidates()
        self.workspace_candidates = self._resolve_workspace_candidates()
        self.active_workspace_orchestrator_id: str | None = None
        self.summary: SetupSummary | None = None
        self._sync_active_workspace_orchestrator()

    @property
    def channel_value(self) -> str:
        if self.slack_enabled and self.telegram_enabled:
            return "both"
        if self.slack_enabled:
            return "slack"
        if self.telegram_enabled:
            return "telegram"
        return "none"

    @property
    def config_preview_text(self) -> str:
        return render_orchestrator_config(
            po_root=self.po_root,
            archive_path=self.archive_path,
            slack_enabled=self.slack_enabled,
            telegram_enabled=self.telegram_enabled,
            default_runtime=self.default_runtime,
            executor_runtime=self.executor_runtime,
            candidates=self.workspace_candidates,
        )

    def _step_text(self, index: int) -> str:
        return f"Step ({index}/{self.TOTAL_STEPS})"

    def _step_title(self, index: int, title: str) -> str:
        return f"{self._step_text(index)} {title}"

    def _step_prompt(self, index: int, message: str) -> str:
        return f"{self._step_text(index)}\n{message}"

    def _render_step(self, index: int, title: str, message: str) -> None:
        self.prompter.clear_screen()
        self.prompter.intro("Project Orchestrator setup")
        self.prompter.note(message, self._step_title(index, title))

    def _selected_workspace_orchestrators(self) -> list[WorkspaceOrchestratorCandidate]:
        return [candidate for candidate in self.workspace_orchestrator_candidates if candidate.selected]

    def _find_workspace_orchestrator_by_id(self, orchestrator_id: str | None) -> WorkspaceOrchestratorCandidate | None:
        if not orchestrator_id:
            return None
        for candidate in self.workspace_orchestrator_candidates:
            if candidate.orchestrator_id == orchestrator_id:
                return candidate
        return None

    def _find_workspace_orchestrator_for_path(self, relative_path: str) -> WorkspaceOrchestratorCandidate | None:
        best_match: WorkspaceOrchestratorCandidate | None = None
        for candidate in self.workspace_orchestrator_candidates:
            base = candidate.relative_path.rstrip("/")
            if relative_path == base or relative_path.startswith(f"{base}/"):
                if best_match is None or len(base) > len(best_match.relative_path):
                    best_match = candidate
        return best_match

    def _sync_active_workspace_orchestrator(self) -> None:
        selected = self._selected_workspace_orchestrators()
        selected_ids = {candidate.orchestrator_id for candidate in selected}
        if self.active_workspace_orchestrator_id not in selected_ids:
            self.active_workspace_orchestrator_id = selected[0].orchestrator_id if selected else None

    def _workspace_candidates_for_active_parent(self) -> list[WorkspaceCandidate]:
        parent = self._find_workspace_orchestrator_by_id(self.active_workspace_orchestrator_id)
        if parent is None:
            return []
        prefix = f"{parent.relative_path}/"
        result = [
            candidate
            for candidate in self.workspace_candidates
            if candidate.relative_path == parent.relative_path or candidate.relative_path.startswith(prefix)
        ]
        result.sort(key=lambda item: (-item.score, item.relative_path))
        return result

    def _workspace_path_relative_to_parent(
        self,
        candidate: WorkspaceCandidate,
        parent: WorkspaceOrchestratorCandidate,
    ) -> str:
        if candidate.relative_path == parent.relative_path:
            return "."
        prefix = f"{parent.relative_path}/"
        if candidate.relative_path.startswith(prefix):
            return candidate.relative_path[len(prefix) :]
        return candidate.relative_path

    def _workspace_orchestrator_summary_text(self) -> str:
        if not self.workspace_orchestrator_candidates:
            return (
                "No Workspace Orchestrator directories were auto-detected.\n"
                "You can add one manually or continue without any selected Workspace Orchestrator entries."
            )

        lines = ["Current Workspace Orchestrator entries:"]
        for index, candidate in enumerate(self.workspace_orchestrator_candidates, start=1):
            mark = "x" if candidate.selected else " "
            markers = ", ".join(candidate.markers) if candidate.markers else "manual"
            lines.append(
                f"{index}. [{mark}] {candidate.orchestrator_id} | "
                f"Environment: {candidate.location}"
            )
            lines.append(f"   markers: {markers}")
        return "\n".join(lines)

    def _workspace_orchestrator_summary_renderable(self) -> RenderableText:
        if not self.workspace_orchestrator_candidates:
            return self._workspace_orchestrator_summary_text()

        tokens: list[tuple[str, str]] = [("", "Current Workspace Orchestrator entries:\n")]
        for index, candidate in enumerate(self.workspace_orchestrator_candidates, start=1):
            mark = "x" if candidate.selected else " "
            markers = ", ".join(candidate.markers) if candidate.markers else "manual"
            tokens.extend(
                [
                    ("", f"{index}. [{mark}] "),
                    ("class:choice-primary-highlighted", candidate.orchestrator_id),
                    ("class:choice-secondary", f"  Environment: {candidate.location}"),
                    ("", "\n"),
                    ("class:choice-secondary", f"   markers: {markers}"),
                ]
            )
            if index < len(self.workspace_orchestrator_candidates):
                tokens.append(("", "\n"))
        return tokens

    def _workspace_summary_text(self) -> str:
        parent = self._find_workspace_orchestrator_by_id(self.active_workspace_orchestrator_id)
        if parent is None:
            return "No parent Workspace Orchestrator is selected."

        candidates = self._workspace_candidates_for_active_parent()
        if not candidates:
            return (
                f"No workspaces are currently registered under `{parent.orchestrator_id}`.\n"
                "Add one manually or refresh workspace discovery for this parent."
            )

        lines = [f"Current workspaces under {parent.orchestrator_id}:"]
        for index, candidate in enumerate(candidates, start=1):
            mark = "x" if candidate.selected else " "
            markers = ", ".join(candidate.markers) if candidate.markers else "manual"
            lines.append(
                f"{index}. [{mark}] {candidate.workspace_id} | "
                f"Path: {self._workspace_path_relative_to_parent(candidate, parent)} | "
                f"Runtime: {candidate.runtime} | Mode: {candidate.mode} | "
                f"Target: {self._format_workspace_remote_target(candidate)}"
            )
            lines.append(f"   markers: {markers}")
        return "\n".join(lines)

    def _workspace_summary_renderable(self) -> RenderableText:
        parent = self._find_workspace_orchestrator_by_id(self.active_workspace_orchestrator_id)
        if parent is None:
            return self._workspace_summary_text()

        candidates = self._workspace_candidates_for_active_parent()
        if not candidates:
            return self._workspace_summary_text()

        tokens: list[tuple[str, str]] = [
            ("", "Current workspaces under "),
            ("class:choice-primary-highlighted", parent.orchestrator_id),
            ("", ":\n"),
        ]
        for index, candidate in enumerate(candidates, start=1):
            mark = "x" if candidate.selected else " "
            markers = ", ".join(candidate.markers) if candidate.markers else "manual"
            tokens.extend(
                [
                    ("", f"{index}. [{mark}] "),
                    ("class:choice-primary-highlighted", candidate.workspace_id),
                    (
                        "class:choice-secondary",
                        f"  Path: {self._workspace_path_relative_to_parent(candidate, parent)} | "
                        f"Runtime: {candidate.runtime} | Mode: {candidate.mode} | "
                        f"Target: {self._format_workspace_remote_target(candidate)}",
                    ),
                    ("", "\n"),
                    ("class:choice-secondary", f"   markers: {markers}"),
                ]
            )
            if index < len(candidates):
                tokens.append(("", "\n"))
        return tokens

    def _selected_parent_banner(self) -> str:
        parent = self._find_workspace_orchestrator_by_id(self.active_workspace_orchestrator_id)
        if parent is None:
            return "No parent Workspace Orchestrator is selected."
        return (
            f"Selected parent Workspace Orchestrator: {parent.orchestrator_id}\n"
            f"Environment: {parent.location}\n"
            f"Target: {self._format_workspace_orchestrator_target(parent)}"
        )

    def _selected_parent_banner_renderable(self) -> RenderableText:
        parent = self._find_workspace_orchestrator_by_id(self.active_workspace_orchestrator_id)
        if parent is None:
            return self._selected_parent_banner()
        return [
            ("", "Selected parent Workspace Orchestrator: "),
            ("class:choice-primary-highlighted", parent.orchestrator_id),
            ("", "\n"),
            ("class:choice-secondary", f"Environment: {parent.location}\n"),
            ("class:choice-secondary", f"Target: {self._format_workspace_orchestrator_target(parent)}"),
        ]

    def _format_workspace_orchestrator_target(self, candidate: WorkspaceOrchestratorCandidate) -> str:
        if candidate.location == "ssh":
            user = str(candidate.remote.get("user", "")).strip()
            host = str(candidate.remote.get("host", "")).strip() or "(host not set)"
            target = f"{user}@{host}" if user else host
            root_path = str(candidate.remote.get("root_path", "")).strip()
            return f"SSH {target}" if not root_path else f"SSH {target} · {root_path}"
        if candidate.location == "kubernetes":
            namespace = str(candidate.remote.get("namespace", "")).strip() or "(namespace not set)"
            pod = str(candidate.remote.get("pod", "")).strip() or "(pod not set)"
            container = str(candidate.remote.get("container", "")).strip()
            root_path = str(candidate.remote.get("root_path", "")).strip()
            target = f"k8s {namespace}/{pod}"
            if container:
                target += f" [{container}]"
            if root_path:
                target += f" · {root_path}"
            return target
        return f"Local · {candidate.relative_path}"

    def _format_workspace_remote_target(self, candidate: WorkspaceCandidate) -> str:
        if candidate.mode != "remote":
            return "local"
        host = str((candidate.remote or {}).get("host", "")).strip() or "(host not set)"
        port = str((candidate.remote or {}).get("port", "9100")).strip() or "9100"
        access = dict((candidate.remote or {}).get("access") or {})
        method = str(access.get("method") or "remote").strip()
        if method == "ssh":
            return f"remote via ssh · {host}:{port}"
        if method == "kubernetes":
            return f"remote via kubernetes · {host}:{port}"
        return f"remote · {host}:{port}"

    def _step_handler(self, step: int) -> Callable[[], StepResult]:
        return {
            1: self._run_intro_step,
            2: self._run_environment_step,
            3: self._run_code_agent_step,
            4: self._run_orchestrator_path_step,
            5: self._run_archive_path_step,
            6: self._run_channel_step,
            7: self._run_default_runtime_step,
            8: self._run_executor_runtime_step,
            9: self._run_workspace_orchestrator_selection_step,
            10: self._run_workspace_selection_step,
            11: self._run_confirmation_step,
        }[step]

    def run(self) -> str:
        """Run the wizard from start to finish."""
        current_step = 1
        try:
            while True:
                result = self._step_handler(current_step)()
                if result == "next":
                    current_step += 1
                    continue
                if result == "stay":
                    continue
                if result == "back":
                    if current_step == 1:
                        if self._confirm_exit_setup():
                            self.prompter.clear_screen()
                            self.prompter.outro("Setup cancelled. No files were written.")
                            return "cancelled"
                        continue
                    current_step -= 1
                    continue
                if result == "cancel":
                    self.prompter.clear_screen()
                    self.prompter.outro("Setup cancelled. No files were written.")
                    return "cancelled"
                if result == "success":
                    return "success"
                raise RuntimeError(f"Unknown step result: {result}")
        except WizardCancelledError:
            self.prompter.clear_screen()
            self.prompter.outro("Setup cancelled. No files were written.")
            return "cancelled"

    def _confirm_exit_setup(self) -> bool:
        self._render_step(1, "Exit setup", "You are at the first step. Exit the setup wizard without writing any files?")
        try:
            return self.prompter.confirm(self._step_prompt(1, "Exit setup now?"), default=False)
        except WizardBackError:
            return False

    def _run_intro_step(self) -> StepResult:
        while True:
            self._render_step(1, "Current folder analysis", format_folder_analysis_text(self.cwd))
            try:
                action = self.prompter.select(
                    self._step_prompt(1, "Choose the next action"),
                    [
                        WizardOption("continue", "Continue", "Move to environment checks"),
                        WizardOption("back", "Back", "Exit setup"),
                    ],
                    default="continue",
                )
            except WizardBackError:
                return "back"
            if action == "back":
                return "back"
            return "next"

    def _run_environment_step(self) -> StepResult:
        while True:
            self._render_step(2, "Environment", environment_summary(self.environment))
            try:
                action = self.prompter.select(
                    self._step_prompt(2, "Choose an environment action"),
                    [
                        WizardOption("continue", "Continue setup", "Use the current environment"),
                        WizardOption(
                            "bootstrap",
                            "Recreate the local environment",
                            "Create the virtualenv again and reinstall dependencies",
                        ),
                        WizardOption("back", "Back", "Return to the previous step"),
                    ],
                    default="continue",
                )
            except WizardBackError:
                return "back"

            if action == "back":
                return "back"
            if action == "continue":
                return "next"

            self._render_step(2, "Bootstrap", "Recreating the local environment. This can take a moment.")
            outputs = bootstrap_project_dependencies(
                self.po_root,
                self.environment.binaries["python"].path or sys.executable,
            )
            self.environment = detect_environment(self.cwd)
            self.prompter.note("\n".join(outputs), "Bootstrap complete")

    def _run_code_agent_step(self) -> StepResult:
        self._render_step(
            3,
            "Code Agent",
            (
                "Choose the primary code agent for this orchestrator.\n"
                "This choice seeds the initial default runtime and executor runtime."
            ),
        )
        try:
            result = self.prompter.select(
                self._step_prompt(3, "Select the primary code agent"),
                [
                    WizardOption("claude", "Claude", "Anthropic Claude CLI"),
                    WizardOption("cursor", "Cursor", "cursor-agent"),
                    WizardOption("codex", "Codex", "OpenAI Codex CLI"),
                    WizardOption("opencode", "OpenCode", "OpenCode CLI"),
                    WizardOption("back", "Back", "Return to the previous step"),
                ],
                default=self.code_agent,
            )
        except WizardBackError:
            return "back"
        if result == "back":
            return "back"
        self.code_agent = result
        self.default_runtime = result
        self.executor_runtime = result
        return "next"

    def _run_orchestrator_path_step(self) -> StepResult:
        self._render_step(
            4,
            "Orchestrator path",
            (
                "Select the directory that contains the projects you work on together.\n"
                "The wizard will place the orchestrator harness there.\n"
                "The harness includes orchestrator.yaml, start-orchestrator.sh, AGENTS.md, and CLAUDE.md."
            ),
        )
        try:
            path = self._prompt_resolved_path(
                message=self._step_prompt(4, "Enter the orchestrator path"),
                default=self.po_root,
                target="orchestrator",
            )
        except WizardBackError:
            return "back"
        self.po_root = path
        if not self.archive_path_is_manual:
            self.archive_path = (self.po_root / "ARCHIVE").resolve()
        self.workspace_orchestrator_candidates = self._resolve_workspace_orchestrator_candidates()
        self.workspace_candidates = self._resolve_workspace_candidates()
        self._sync_active_workspace_orchestrator()
        return "next"

    def _run_archive_path_step(self) -> StepResult:
        self._render_step(
            5,
            "Archive path",
            (
                "Choose where channel credentials and setup secrets should live.\n"
                "This is usually an ARCHIVE directory inside the orchestrator path."
            ),
        )
        try:
            path = self._prompt_resolved_path(
                message=self._step_prompt(5, "Enter the archive path"),
                default=self.archive_path,
                target="archive",
            )
        except WizardBackError:
            return "back"
        self.archive_path = path
        self.archive_path_is_manual = self.archive_path != (self.po_root / "ARCHIVE").resolve()
        return "next"

    def _run_channel_step(self) -> StepResult:
        self._render_step(
            6,
            "Channels",
            (
                "Choose the initial channel configuration for this orchestrator.\n"
                "You can start with no channels and configure Slack or Telegram later."
            ),
        )
        try:
            channel = self.prompter.select(
                self._step_prompt(6, "Choose the initial channel configuration"),
                [
                    WizardOption("none", "None", "Start without Slack or Telegram"),
                    WizardOption("slack", "Slack", "Enable Slack only"),
                    WizardOption("telegram", "Telegram", "Enable Telegram only"),
                    WizardOption("both", "Both", "Enable both Slack and Telegram"),
                    WizardOption("back", "Back", "Return to the previous step"),
                ],
                default=self.channel_value,
            )
        except WizardBackError:
            return "back"
        if channel == "back":
            return "back"
        self.slack_enabled, self.telegram_enabled = CHANNEL_STATES[channel]
        if not self.slack_enabled:
            self.slack_credentials = {}
        if not self.telegram_enabled:
            self.telegram_credentials = {}
        try:
            self._collect_channel_credentials(step_index=6)
        except WizardBackError:
            return "back"
        return "next"

    def _credential_validator(self, label: str, allow_empty: bool = False) -> Callable[[str], str | None]:
        def validate(value: str) -> str | None:
            if allow_empty:
                return None
            if not value.strip():
                return f"{label} is required."
            return None

        return validate

    def _prompt_secret_value(
        self,
        step_index: int,
        label: str,
        *,
        allow_empty: bool = False,
    ) -> str:
        return self.prompter.secret(
            self._step_prompt(step_index, label),
            default="",
            validate=self._credential_validator(label, allow_empty=allow_empty),
        ).strip()

    def _collect_slack_credentials(self, step_index: int) -> None:
        self.prompter.clear_screen()
        self.prompter.intro("Project Orchestrator setup")
        self.prompter.note(
            (
                "Enter the Slack credentials needed to connect this orchestrator.\n"
                "Each value is masked while you type.\n"
                "After setup finishes, these values will be written to ARCHIVE/slack/credentials and the channel runtime will read them from there."
            ),
            self._step_title(step_index, "Slack credentials"),
        )
        self.slack_credentials = {
            "app_id": self._prompt_secret_value(step_index, "Slack app_id"),
            "client_id": self._prompt_secret_value(step_index, "Slack client_id"),
            "client_secret": self._prompt_secret_value(step_index, "Slack client_secret"),
            "signing_secret": self._prompt_secret_value(step_index, "Slack signing_secret"),
            "app_level_token": self._prompt_secret_value(step_index, "Slack app_level_token"),
            "bot_token": self._prompt_secret_value(step_index, "Slack bot_token (optional)", allow_empty=True),
        }

    def _collect_telegram_credentials(self, step_index: int) -> None:
        self.prompter.clear_screen()
        self.prompter.intro("Project Orchestrator setup")
        self.prompter.note(
            (
                "Enter the Telegram credentials needed to connect this orchestrator.\n"
                "Each value is masked while you type.\n"
                "After setup finishes, these values will be written to ARCHIVE/telegram/credentials and the channel runtime will read them from there."
            ),
            self._step_title(step_index, "Telegram credentials"),
        )
        self.telegram_credentials = {
            "bot_token": self._prompt_secret_value(step_index, "Telegram bot_token"),
            "allowed_users": self._prompt_secret_value(step_index, "Telegram allowed_users (optional)", allow_empty=True),
        }

    def _collect_channel_credentials(self, step_index: int) -> None:
        if self.slack_enabled:
            self._collect_slack_credentials(step_index)
        if self.telegram_enabled:
            self._collect_telegram_credentials(step_index)

    def _run_default_runtime_step(self) -> StepResult:
        self._render_step(
            7,
            "Default Runtime",
            "Choose the default runtime used when a role or workspace does not override it.",
        )
        try:
            runtime = self._prompt_runtime(
                message=self._step_prompt(7, "Select the default runtime"),
                default=self.default_runtime,
                allow_back=True,
            )
        except WizardBackError:
            return "back"
        if runtime == "back":
            return "back"
        self.default_runtime = runtime
        return "next"

    def _run_executor_runtime_step(self) -> StepResult:
        self._render_step(
            8,
            "Executor Runtime",
            (
                "Choose the executor runtime used for workspace execution by default.\n"
                "A workspace can still override its own runtime later."
            ),
        )
        try:
            runtime = self._prompt_runtime(
                message=self._step_prompt(8, "Select the executor runtime"),
                default=self.executor_runtime,
                allow_back=True,
            )
        except WizardBackError:
            return "back"
        if runtime == "back":
            return "back"
        self.executor_runtime = runtime
        return "next"

    def _run_workspace_orchestrator_selection_step(self) -> StepResult:
        while True:
            self._render_step(
                9,
                "Workspace Orchestrator selection",
                (
                    "A workspace is the place where you directly work with a code agent and write code.\n"
                    "A Workspace Orchestrator holds the project-level context across related workspaces.\n"
                    "For example, the backend and frontend of one site belong to the same project context.\n"
                    "That means the Workspace Orchestrator should understand that if the backend API changes, the frontend may need to change too.\n"
                    "In this step, choose the project directories that should act as Workspace Orchestrators.\n"
                    "The actual workspaces inside those project directories are selected in the next step."
                ),
            )
            self.prompter.note(self._workspace_orchestrator_summary_renderable(), "Current entries")
            try:
                action = self.prompter.select(
                    self._step_prompt(9, "Choose a Workspace Orchestrator action"),
                    self._workspace_orchestrator_action_options(),
                    default="continue" if self.workspace_orchestrator_candidates else "add",
                )
            except WizardBackError:
                return "back"

            if action == "back":
                return "back"
            if action == "continue":
                self.workspace_candidates = self._resolve_workspace_candidates()
                self._sync_active_workspace_orchestrator()
                return "next"
            if action == "refresh":
                self.workspace_orchestrator_candidates = self._resolve_workspace_orchestrator_candidates()
                self.workspace_candidates = self._resolve_workspace_candidates()
                self._sync_active_workspace_orchestrator()
                continue
            if action == "add":
                try:
                    candidate = self._prompt_workspace_orchestrator_details()
                except WizardBackError:
                    continue
                self.workspace_orchestrator_candidates.append(candidate)
                self.workspace_candidates = self._resolve_workspace_candidates()
                self._sync_active_workspace_orchestrator()
                continue
            if action == "toggle":
                if self._prompt_workspace_orchestrator_selection():
                    self.workspace_candidates = self._resolve_workspace_candidates()
                    self._sync_active_workspace_orchestrator()
                continue

            try:
                index = self._select_workspace_orchestrator_index()
            except WizardBackError:
                continue
            if index is None:
                continue

            if action == "edit":
                try:
                    self.workspace_orchestrator_candidates[index] = self._prompt_workspace_orchestrator_details(
                        self.workspace_orchestrator_candidates[index]
                    )
                except WizardBackError:
                    continue
                self.workspace_candidates = self._resolve_workspace_candidates()
                self._sync_active_workspace_orchestrator()
                continue

    def _run_workspace_selection_step(self) -> StepResult:
        self.workspace_candidates = self._resolve_workspace_candidates()
        self._sync_active_workspace_orchestrator()
        while True:
            self._render_step(
                10,
                "Workspace selection",
                (
                    "Now choose the actual workspaces inside the selected Workspace Orchestrator directories.\n"
                    "A workspace is the directory where a code agent will actually run and modify code.\n"
                    "If the parent Workspace Orchestrator is remote, this step also captures the remote listener details for that workspace.\n"
                    "Only these workspace entries will be written to orchestrator.yaml."
                ),
            )
            selected_orchestrators = self._selected_workspace_orchestrators()
            if not selected_orchestrators:
                self.prompter.note(
                    "No Workspace Orchestrators are selected right now. Go back and enable at least one project directory first.",
                    "Current parent",
                )
                try:
                    action = self.prompter.select(
                        self._step_prompt(10, "Choose an action"),
                        [
                            WizardOption("continue", "Continue", "Write a config without any workspaces"),
                            WizardOption("back", "Back", "Return to the previous step"),
                            WizardOption("refresh", "Refresh workspace discovery", "Reload workspace candidates"),
                        ],
                        default="continue",
                    )
                except WizardBackError:
                    return "back"
                if action == "continue":
                    return "next"
                if action == "back":
                    return "back"
                self.workspace_candidates = self._resolve_workspace_candidates()
                self._sync_active_workspace_orchestrator()
                continue

            try:
                parent_id = self._select_parent_workspace_orchestrator()
            except WizardBackError:
                return "back"
            if parent_id == "back":
                return "back"
            if parent_id == "continue":
                errors = validate_workspace_candidates(self.workspace_candidates)
                if errors:
                    self.prompter.clear_screen()
                    self.prompter.intro("Project Orchestrator setup")
                    self.prompter.note(
                        "Workspace validation failed:\n" + "\n".join(f"- {error}" for error in errors),
                        "Workspace validation",
                    )
                    continue
                return "next"
            if parent_id == "refresh":
                self.workspace_candidates = self._resolve_workspace_candidates()
                self._sync_active_workspace_orchestrator()
                continue
            assert parent_id is not None
            self.active_workspace_orchestrator_id = parent_id
            result = self._run_workspace_parent_editor()
            if result == "back":
                continue
            if result == "cancel":
                return "back"

    def _run_workspace_parent_editor(self) -> StepResult:
        while True:
            self.prompter.clear_screen()
            self.prompter.intro("Project Orchestrator setup")
            self.prompter.note(
                (
                    "Now choose the actual workspaces inside the selected Workspace Orchestrator directories.\n"
                    "A workspace is the directory where a code agent will actually run and modify code.\n"
                    "If the parent Workspace Orchestrator is remote, this step also captures the remote listener details for that workspace.\n"
                    "Only these workspace entries will be written to orchestrator.yaml."
                ),
                self._step_title(10, "Workspace selection"),
            )
            self.prompter.note(self._selected_parent_banner_renderable(), "Parent Workspace Orchestrator")
            self.prompter.note(self._workspace_summary_renderable(), "Current entries")
            try:
                action = self.prompter.select(
                    self._step_prompt(10, "Choose a workspace action"),
                    self._workspace_action_options(),
                    default="done" if self._workspace_candidates_for_active_parent() else "add",
                )
            except WizardBackError:
                return "back"

            if action == "done":
                return "back"
            if action == "back":
                return "cancel"
            if action == "refresh":
                self.workspace_candidates = self._resolve_workspace_candidates()
                self._sync_active_workspace_orchestrator()
                continue

            current_parent = self._find_workspace_orchestrator_by_id(self.active_workspace_orchestrator_id)
            if current_parent is None:
                return "back"

            if action == "add":
                try:
                    candidate = self._prompt_workspace_details(default_parent=current_parent, lock_parent=True)
                except WizardBackError:
                    continue
                self.workspace_candidates.append(candidate)
                continue

            if action == "toggle":
                self._prompt_workspace_selection()
                continue

            try:
                candidate = self._select_workspace_candidate()
            except WizardBackError:
                continue
            if candidate is None:
                continue

            if action == "edit":
                index = self.workspace_candidates.index(candidate)
                try:
                    updated = self._prompt_workspace_details(
                        candidate,
                        default_parent=current_parent,
                        lock_parent=True,
                    )
                except WizardBackError:
                    continue
                self.workspace_candidates[index] = updated
                continue

    def _run_confirmation_step(self) -> StepResult:
        while True:
            self._render_step(11, "Final Confirmation", "Review the generated orchestrator config below.")
            self.prompter.note(self.config_preview_text, "Config preview")
            try:
                should_write = self.prompter.confirm(self._step_prompt(11, "Write setup files now?"), default=True)
            except WizardBackError:
                return "back"
            if should_write:
                self.summary = write_setup_files(
                    po_root=self.po_root,
                    archive_path=self.archive_path,
                    slack_enabled=self.slack_enabled,
                    telegram_enabled=self.telegram_enabled,
                    default_runtime=self.default_runtime,
                    executor_runtime=self.executor_runtime,
                    candidates=self.workspace_candidates,
                    slack_credentials=self.slack_credentials,
                    telegram_credentials=self.telegram_credentials,
                    python_bin=self.environment.binaries["python"].path or sys.executable,
                )
                self.prompter.clear_screen()
                self.prompter.outro(final_instruction_text(self.summary))
                return "success"

            self._render_step(11, "Final Confirmation", "No files were written yet.")
            try:
                next_action = self.prompter.select(
                    self._step_prompt(11, "What would you like to do next?"),
                    [
                        WizardOption("back", "Back", "Return to Workspace selection"),
                        WizardOption("cancel", "Cancel setup", "Exit without writing any files"),
                    ],
                    default="back",
                )
            except WizardBackError:
                return "back"
            if next_action == "back":
                return "back"
            if next_action == "cancel":
                return "cancel"

    def _workspace_orchestrator_action_options(self) -> list[WizardOption]:
        options = [WizardOption("continue", "Continue", "Use the current Workspace Orchestrator list")]
        if self.workspace_orchestrator_candidates:
            options.extend(
                [
                    WizardOption(
                        "toggle",
                        "Toggle Workspace Orchestrator selection",
                        "Enable or disable multiple Workspace Orchestrator entries at once",
                    ),
                    WizardOption(
                        "edit",
                        "Edit Workspace Orchestrator",
                        "Change the id, directory, environment, or selection",
                    ),
                ]
            )
        options.extend(
            [
                WizardOption("add", "Add Workspace Orchestrator", "Create a local, SSH, or Kubernetes entry"),
                WizardOption("refresh", "Refresh discovery", "Reload configured and auto-detected entries"),
                WizardOption("back", "Back", "Return to the previous step"),
            ]
        )
        return options

    def _workspace_action_options(self) -> list[WizardOption]:
        options = [WizardOption("done", "Done with this Workspace Orchestrator", "Return to the Workspace Orchestrator list")]
        if self._workspace_candidates_for_active_parent():
            options.extend(
                [
                    WizardOption("toggle", "Toggle Workspace selection", "Enable or disable multiple workspace entries at once"),
                    WizardOption("edit", "Edit Workspace", "Change the workspace id, path, runtime, mode, or remote info"),
                ]
            )
        options.extend(
            [
                WizardOption("add", "Add Workspace", "Create a local or remote workspace entry for this parent"),
                WizardOption("refresh", "Refresh workspace discovery", "Reload workspaces for the selected parents"),
                WizardOption("back", "Back", "Return to the previous step"),
            ]
        )
        return options

    def _prompt_runtime(self, message: str, default: str, allow_back: bool = False) -> str:
        options = [
            WizardOption("claude", "Claude", "Anthropic Claude CLI"),
            WizardOption("cursor", "Cursor", "cursor-agent"),
            WizardOption("codex", "Codex", "OpenAI Codex CLI"),
            WizardOption("opencode", "OpenCode", "OpenCode CLI"),
        ]
        if allow_back:
            options.append(WizardOption("back", "Back", "Return to the previous step"))
        return self.prompter.select(message, options, default=default)

    def _prompt_resolved_path(self, message: str, default: Path, target: str) -> Path:
        def validate(value: str) -> str | None:
            resolved, error = resolve_setup_input_path(value, self.cwd, default)
            if error:
                return error
            assert resolved is not None
            return validate_setup_target_path(resolved, target).error or None

        raw = self.prompter.text(message, default=str(default), validate=validate)
        resolved, error = resolve_setup_input_path(raw, self.cwd, default)
        if error or resolved is None:  # pragma: no cover
            raise RuntimeError(error or "Could not resolve setup path.")
        validation = validate_setup_target_path(resolved, target)
        if validation.error:  # pragma: no cover
            raise RuntimeError(validation.error)
        return resolved

    def _resolve_workspace_orchestrator_candidates(self) -> list[WorkspaceOrchestratorCandidate]:
        return suggested_workspace_orchestrator_candidates_for_root(self.cwd, self.po_root)

    def _resolve_workspace_candidates(self) -> list[WorkspaceCandidate]:
        configured = candidates_from_config(load_setup_config(self.po_root))
        configured_by_path = {candidate.relative_path: candidate for candidate in configured}
        existing_by_path = {
            candidate.relative_path: candidate
            for candidate in getattr(self, "workspace_candidates", [])
        }

        resolved: list[WorkspaceCandidate] = []
        seen_paths: set[str] = set()
        for orchestrator in self.workspace_orchestrator_candidates:
            if not orchestrator.selected:
                continue
            discovered = workspace_candidates_for_orchestrator(
                self.po_root,
                orchestrator,
                configured_workspaces=configured,
            )
            for candidate in discovered:
                existing = existing_by_path.get(candidate.relative_path)
                configured_candidate = configured_by_path.get(candidate.relative_path)
                if existing is not None:
                    candidate.workspace_id = existing.workspace_id
                    candidate.selected = existing.selected
                    candidate.runtime = existing.runtime
                    candidate.mode = existing.mode
                    candidate.markers = existing.markers
                    candidate.remote = existing.remote
                elif configured_candidate is not None:
                    candidate.workspace_id = configured_candidate.workspace_id
                    candidate.selected = configured_candidate.selected
                    candidate.runtime = configured_candidate.runtime
                    candidate.mode = configured_candidate.mode
                    candidate.markers = configured_candidate.markers
                    candidate.remote = configured_candidate.remote
                else:
                    candidate.runtime = self.executor_runtime
                if candidate.relative_path in seen_paths:
                    continue
                seen_paths.add(candidate.relative_path)
                resolved.append(candidate)
        resolved.sort(key=lambda item: (-item.score, item.relative_path))
        return resolved

    def _prompt_workspace_orchestrator_selection(self) -> bool:
        defaults = [
            str(index)
            for index, candidate in enumerate(self.workspace_orchestrator_candidates)
            if candidate.selected
        ]
        try:
            selected_indexes = self.prompter.multiselect(
                self._step_prompt(9, "Select the Workspace Orchestrator entries that should stay enabled"),
                [
                    WizardOption(
                        str(index),
                        candidate.orchestrator_id,
                        (
                            f"Environment: {candidate.location} | "
                            f"{'selected' if candidate.selected else 'not selected'}"
                        ),
                        highlight=True,
                    )
                    for index, candidate in enumerate(self.workspace_orchestrator_candidates)
                ],
                defaults=defaults,
            )
        except WizardBackError:
            return False

        try:
            decision = self.prompter.select(
                self._step_prompt(9, "Apply the updated Workspace Orchestrator selection?"),
                [
                    WizardOption("confirm", "Confirm", "Apply the selection changes"),
                    WizardOption("cancel", "Cancel", "Discard the selection changes"),
                    WizardOption("back", "Back", "Return to the previous screen"),
                ],
                default="confirm",
            )
        except WizardBackError:
            return False
        if decision != "confirm":
            return False

        selected_set = set(selected_indexes)
        for index, candidate in enumerate(self.workspace_orchestrator_candidates):
            candidate.selected = str(index) in selected_set
        return True

    def _prompt_workspace_selection(self) -> bool:
        current_candidates = self._workspace_candidates_for_active_parent()
        defaults = [
            str(index)
            for index, candidate in enumerate(current_candidates)
            if candidate.selected
        ]
        try:
            selected_indexes = self.prompter.multiselect(
                self._step_prompt(10, "Select the workspace entries that should stay enabled"),
                [
                    WizardOption(
                        str(index),
                        candidate.workspace_id,
                        (
                            f"Path: {self._workspace_path_relative_to_parent(candidate, self._find_workspace_orchestrator_by_id(self.active_workspace_orchestrator_id))} | "
                            f"{candidate.runtime}, {candidate.mode}, {self._format_workspace_remote_target(candidate)}, "
                            f"{'selected' if candidate.selected else 'not selected'}"
                        ),
                        highlight=True,
                    )
                    for index, candidate in enumerate(current_candidates)
                ],
                defaults=defaults,
            )
        except WizardBackError:
            return False

        try:
            decision = self.prompter.select(
                self._step_prompt(10, "Apply the updated workspace selection?"),
                [
                    WizardOption("confirm", "Confirm", "Apply the selection changes"),
                    WizardOption("cancel", "Cancel", "Discard the selection changes"),
                    WizardOption("back", "Back", "Return to the previous screen"),
                ],
                default="confirm",
            )
        except WizardBackError:
            return False
        if decision != "confirm":
            return False

        selected_set = set(selected_indexes)
        for index, candidate in enumerate(current_candidates):
            candidate.selected = str(index) in selected_set
        return True

    def _select_workspace_orchestrator_index(self) -> int | None:
        if not self.workspace_orchestrator_candidates:
            return None

        choice = self.prompter.select(
            self._step_prompt(9, "Select a Workspace Orchestrator entry"),
            [
                WizardOption(
                    str(index),
                    candidate.orchestrator_id,
                    (
                        f"Environment: {candidate.location} | "
                        f"{'selected' if candidate.selected else 'not selected'}"
                    ),
                    highlight=True,
                )
                for index, candidate in enumerate(self.workspace_orchestrator_candidates)
            ]
            + [WizardOption("back", "Back", "Return to Workspace Orchestrator actions")],
            default="0",
        )
        if choice == "back":
            return None
        return int(choice)

    def _select_parent_workspace_orchestrator(self) -> str | None:
        selected = self._selected_workspace_orchestrators()
        if not selected:
            return None
        choice = self.prompter.select(
            self._step_prompt(10, "Choose a Workspace Orchestrator to manage, or continue to final confirmation"),
            [
                WizardOption(
                    candidate.orchestrator_id,
                    candidate.orchestrator_id,
                    f"Environment: {candidate.location}",
                    highlight=True,
                )
                for candidate in selected
            ]
            + [
                WizardOption("continue", "Continue to final confirmation", "Move to the final review screen"),
                WizardOption("refresh", "Refresh workspace discovery", "Reload workspaces for the selected parents"),
                WizardOption("back", "Back", "Return to the previous step"),
            ],
            default=self.active_workspace_orchestrator_id or selected[0].orchestrator_id,
        )
        return choice

    def _select_workspace_candidate(self) -> WorkspaceCandidate | None:
        current_candidates = self._workspace_candidates_for_active_parent()
        if not current_candidates:
            return None
        choice = self.prompter.select(
            self._step_prompt(10, "Select a workspace entry"),
            [
                WizardOption(
                    str(index),
                    candidate.workspace_id,
                    (
                        f"Path: {self._workspace_path_relative_to_parent(candidate, self._find_workspace_orchestrator_by_id(self.active_workspace_orchestrator_id))} | "
                        f"{candidate.runtime}, {candidate.mode}, {self._format_workspace_remote_target(candidate)}, "
                        f"{'selected' if candidate.selected else 'not selected'}"
                    ),
                    highlight=True,
                )
                for index, candidate in enumerate(current_candidates)
            ]
            + [WizardOption("back", "Back", "Return to workspace actions")],
            default="0",
        )
        if choice == "back":
            return None
        return current_candidates[int(choice)]

    def _prompt_remote_environment(self, default: str, step_index: int) -> str:
        return self.prompter.select(
            self._step_prompt(step_index, "Select the Workspace Orchestrator environment"),
            [
                WizardOption("local", "Local", "The project directory is on this machine"),
                WizardOption("ssh", "SSH", "The project directory is on another machine reached by SSH"),
                WizardOption("kubernetes", "Kubernetes", "The project directory is inside a pod or container"),
                WizardOption("back", "Back", "Return to the previous screen"),
            ],
            default=default if default in REMOTE_ENV_VALUES else "local",
        )

    def _prompt_ssh_access_details(
        self,
        existing: dict[str, object] | None = None,
        step_index: int = 9,
    ) -> dict[str, object]:
        existing = existing or {}
        host = self.prompter.text(
            self._step_prompt(step_index, "SSH host"),
            default=str(existing.get("host", "")),
            validate=lambda value: validate_non_empty(value, "SSH host"),
        ).strip()
        user = self.prompter.text(
            self._step_prompt(step_index, "SSH user"),
            default=str(existing.get("user", "")),
        ).strip()
        key_file = self.prompter.text(
            self._step_prompt(step_index, "SSH key file (optional)"),
            default=str(existing.get("key_file", "")),
        ).strip()
        root_path = self.prompter.text(
            self._step_prompt(step_index, "Project root path on the SSH host"),
            default=str(existing.get("root_path", "")),
            validate=lambda value: validate_non_empty(value, "Project root path"),
        ).strip()
        remote: dict[str, object] = {
            "method": "ssh",
            "host": host,
            "root_path": root_path,
        }
        if user:
            remote["user"] = user
        if key_file:
            remote["key_file"] = key_file
        return remote

    def _prompt_kubernetes_access_details(
        self,
        existing: dict[str, object] | None = None,
        step_index: int = 9,
    ) -> dict[str, object]:
        existing = existing or {}
        namespace = self.prompter.text(
            self._step_prompt(step_index, "Kubernetes namespace"),
            default=str(existing.get("namespace", "")),
            validate=lambda value: validate_non_empty(value, "Kubernetes namespace"),
        ).strip()
        pod = self.prompter.text(
            self._step_prompt(step_index, "Kubernetes pod"),
            default=str(existing.get("pod", "")),
            validate=lambda value: validate_non_empty(value, "Kubernetes pod"),
        ).strip()
        container = self.prompter.text(
            self._step_prompt(step_index, "Container name (optional)"),
            default=str(existing.get("container", "")),
        ).strip()
        kubeconfig = self.prompter.text(
            self._step_prompt(step_index, "kubeconfig path (optional)"),
            default=str(existing.get("kubeconfig", "")),
        ).strip()
        root_path = self.prompter.text(
            self._step_prompt(step_index, "Project root path inside the pod or container"),
            default=str(existing.get("root_path", "")),
            validate=lambda value: validate_non_empty(value, "Project root path"),
        ).strip()
        remote: dict[str, object] = {
            "method": "kubernetes",
            "namespace": namespace,
            "pod": pod,
            "root_path": root_path,
        }
        if container:
            remote["container"] = container
        if kubeconfig:
            remote["kubeconfig"] = kubeconfig
        return remote

    def _prompt_access_details_for_environment(
        self,
        environment: str,
        existing: dict[str, object] | None = None,
        step_index: int = 9,
    ) -> dict[str, object]:
        if environment == "ssh":
            return self._prompt_ssh_access_details(existing, step_index=step_index)
        if environment == "kubernetes":
            return self._prompt_kubernetes_access_details(existing, step_index=step_index)
        return {}

    def _default_listener_host_from_access(self, access: dict[str, object] | None) -> str:
        access = access or {}
        method = str(access.get("method", "")).strip()
        if method == "ssh":
            return str(access.get("host", "")).strip()
        if method == "kubernetes":
            pod = str(access.get("pod", "")).strip()
            namespace = str(access.get("namespace", "")).strip()
            if pod and namespace:
                return f"{pod}.{namespace}"
            return pod or namespace
        return ""

    def _prompt_remote_listener_details(
        self,
        access: dict[str, object],
        existing_remote: dict[str, object] | None = None,
        default_remote_cwd: str = "",
        step_index: int = 10,
    ) -> dict[str, object]:
        existing_remote = existing_remote or {}
        existing_access = dict(existing_remote.get("access") or {})
        access_method = str(access.get("method", "")).strip() or str(existing_access.get("method", "")).strip()
        base_access = dict(access)
        if access_method and not base_access.get("method"):
            base_access["method"] = access_method

        listener_host = self.prompter.text(
            self._step_prompt(step_index, "Remote listener host reachable from the Project Orchestrator"),
            default=str(existing_remote.get("host") or self._default_listener_host_from_access(base_access)),
            validate=lambda value: validate_non_empty(value, "Remote listener host"),
        ).strip()
        listener_port = self.prompter.text(
            self._step_prompt(step_index, "Remote listener port"),
            default=str(existing_remote.get("port", 9100)),
            validate=validate_port_text,
        ).strip()
        listener_token = self.prompter.text(
            self._step_prompt(step_index, "Remote listener token (optional)"),
            default=str(existing_remote.get("token", "")),
        ).strip()
        remote_cwd = self.prompter.text(
            self._step_prompt(step_index, "Remote workspace path used by the listener"),
            default=str(existing_access.get("cwd") or default_remote_cwd),
            validate=lambda value: validate_non_empty(value, "Remote workspace path"),
        ).strip()
        access_payload = dict(base_access)
        access_payload["cwd"] = remote_cwd
        return {
            "host": listener_host,
            "port": int(listener_port),
            "token": listener_token,
            "access": access_payload,
        }

    def _prompt_workspace_orchestrator_details(
        self,
        existing: WorkspaceOrchestratorCandidate | None = None,
    ) -> WorkspaceOrchestratorCandidate:
        candidate = existing or WorkspaceOrchestratorCandidate(
            orchestrator_id="workspace-orchestrator",
            relative_path="project",
            score=0,
            markers=["manual"],
            selected=True,
        )

        orchestrator_id = self.prompter.text(
            self._step_prompt(9, "Workspace Orchestrator id"),
            default=candidate.orchestrator_id,
            validate=validate_workspace_id,
        ).strip()
        relative_path = self.prompter.text(
            self._step_prompt(9, "Workspace Orchestrator directory relative to the orchestrator path"),
            default=candidate.relative_path,
            validate=validate_workspace_orchestrator_relative_path,
        ).strip()
        location = self._prompt_remote_environment(candidate.location, step_index=9)
        if location == "back":
            raise WizardBackError()
        remote_details: dict[str, object] = {}
        if location != "local":
            self.prompter.clear_screen()
            self.prompter.intro("Project Orchestrator setup")
            self.prompter.note(
                (
                    "This Workspace Orchestrator lives outside the local machine.\n"
                    "The details you enter here are reused as defaults when you add remote workspaces in the next step."
                ),
                "Remote Workspace Orchestrator",
            )
            remote_details = self._prompt_access_details_for_environment(location, candidate.remote, step_index=9)
        selected = self.prompter.confirm(
            self._step_prompt(9, "Include this Workspace Orchestrator in the next workspace selection step?"),
            default=candidate.selected,
        )
        markers = list(candidate.markers) if candidate.markers else ["manual"]
        return WorkspaceOrchestratorCandidate(
            orchestrator_id=orchestrator_id,
            relative_path=relative_path,
            score=candidate.score,
            markers=markers,
            selected=selected,
            location=location,
            remote=remote_details,
        )

    def _prompt_workspace_details(
        self,
        existing: WorkspaceCandidate | None = None,
        default_parent: WorkspaceOrchestratorCandidate | None = None,
        lock_parent: bool = False,
    ) -> WorkspaceCandidate:
        candidate = existing or WorkspaceCandidate(
            workspace_id="workspace",
            relative_path="workspace",
            score=0,
            markers=["manual"],
            selected=True,
            runtime=self.executor_runtime,
            mode="local",
        )

        selected_orchestrators = self._selected_workspace_orchestrators()
        if not selected_orchestrators:
            raise RuntimeError("At least one Workspace Orchestrator must be selected before configuring workspaces.")

        current_parent = default_parent or self._find_workspace_orchestrator_for_path(candidate.relative_path)
        if current_parent is None or current_parent not in selected_orchestrators:
            current_parent = selected_orchestrators[0]
        if lock_parent:
            parent_orchestrator = current_parent
        else:
            parent_choice = self.prompter.select(
                self._step_prompt(10, "Select the parent Workspace Orchestrator"),
                [
                    WizardOption(
                        option.orchestrator_id,
                        option.orchestrator_id,
                        f"Environment: {option.location}",
                        highlight=True,
                    )
                    for option in selected_orchestrators
                ]
                + [WizardOption("back", "Back", "Return to the previous screen")],
                default=current_parent.orchestrator_id,
            )
            if parent_choice == "back":
                raise WizardBackError()
            parent_orchestrator = next(option for option in selected_orchestrators if option.orchestrator_id == parent_choice)

        if candidate.relative_path == parent_orchestrator.relative_path:
            workspace_relative_to_parent = "."
        elif candidate.relative_path.startswith(f"{parent_orchestrator.relative_path}/"):
            workspace_relative_to_parent = candidate.relative_path[len(parent_orchestrator.relative_path) + 1 :]
        else:
            workspace_relative_to_parent = "."

        workspace_id = self.prompter.text(
            self._step_prompt(10, "Workspace id"),
            default=candidate.workspace_id,
            validate=validate_workspace_id,
        ).strip()
        workspace_relative_to_parent = self.prompter.text(
            self._step_prompt(10, "Workspace path relative to the selected Workspace Orchestrator"),
            default=workspace_relative_to_parent,
            validate=validate_workspace_relative_path,
        ).strip()
        relative_path = (
            parent_orchestrator.relative_path
            if workspace_relative_to_parent in {".", ""}
            else f"{parent_orchestrator.relative_path}/{workspace_relative_to_parent}".strip("/")
        )
        runtime = self._prompt_runtime(self._step_prompt(10, "Workspace runtime"), candidate.runtime, allow_back=True)
        if runtime == "back":
            raise WizardBackError()

        inherited_location = parent_orchestrator.location
        remote_details = dict(candidate.remote or {})
        if inherited_location != "local":
            mode = "remote"
            self.prompter.clear_screen()
            self.prompter.intro("Project Orchestrator setup")
            self.prompter.note(
                (
                    f"The parent Workspace Orchestrator uses the {inherited_location} environment.\n"
                    "This workspace will be configured as a remote workspace."
                ),
                "Remote workspace",
            )
            base_root = str(parent_orchestrator.remote.get("root_path", "")).strip()
            default_remote_cwd = base_root
            if workspace_relative_to_parent not in {".", ""} and base_root:
                default_remote_cwd = f"{base_root.rstrip('/')}/{workspace_relative_to_parent.lstrip('./')}"
            remote_details = self._prompt_remote_listener_details(
                access=parent_orchestrator.remote,
                existing_remote=remote_details,
                default_remote_cwd=default_remote_cwd,
                step_index=10,
            )
            mode = "remote"
        else:
            mode = self.prompter.select(
                self._step_prompt(10, "Workspace mode"),
                [
                    WizardOption("local", "Local", "Run in the local workspace"),
                    WizardOption("remote", "Remote", "Connect through the remote listener"),
                    WizardOption("back", "Back", "Return to the previous screen"),
                ],
                default=candidate.mode,
            )
            if mode == "back":
                raise WizardBackError()
            if mode == "remote":
                remote_method = self.prompter.select(
                    self._step_prompt(10, "Select the remote environment for this workspace"),
                    [
                        WizardOption("ssh", "SSH", "The workspace listener runs on another machine"),
                        WizardOption("kubernetes", "Kubernetes", "The workspace listener runs in a pod or container"),
                        WizardOption("back", "Back", "Return to the previous screen"),
                    ],
                    default=str((remote_details.get("access") or {}).get("method") or "ssh"),
                )
                if remote_method == "back":
                    raise WizardBackError()
                access_details = self._prompt_access_details_for_environment(
                    remote_method,
                    dict((remote_details.get("access") or {})),
                    step_index=10,
                )
                base_root = str(access_details.get("root_path", "")).strip()
                default_remote_cwd = base_root
                if workspace_relative_to_parent not in {".", ""} and base_root:
                    default_remote_cwd = f"{base_root.rstrip('/')}/{workspace_relative_to_parent.lstrip('./')}"
                remote_details = self._prompt_remote_listener_details(
                    access=access_details,
                    existing_remote=remote_details,
                    default_remote_cwd=default_remote_cwd,
                    step_index=10,
                )
            else:
                remote_details = {}

        selected = self.prompter.confirm(
            self._step_prompt(10, "Include this workspace in the generated config?"),
            default=candidate.selected,
        )
        markers = list(candidate.markers) if candidate.markers else ["manual"]
        return WorkspaceCandidate(
            workspace_id=workspace_id,
            relative_path=relative_path,
            score=candidate.score,
            markers=markers,
            selected=selected,
            runtime=runtime,
            mode=mode,
            remote=remote_details,
        )


def main() -> None:
    """Run the interactive setup wizard."""
    wizard = SetupWizard()
    result = wizard.run()
    if result == "success":
        launch_post_setup_runtime(
            runtime=wizard.default_runtime,
            po_root=wizard.po_root,
            archive_path=wizard.archive_path,
            workspace_orchestrator_candidates=wizard.workspace_orchestrator_candidates,
        )
        raise SystemExit(0)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
