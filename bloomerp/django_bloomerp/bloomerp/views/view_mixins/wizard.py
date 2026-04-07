from typing import Any, Callable, Type
from dataclasses import dataclass
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect



class BaseStateOrchestrator:
    session_key: str
    
    def __init__(self, request: HttpRequest, session_key: str):
        self.request = request
        self.user = request.user
        self.session_key = session_key
    
    def _get_state(self) -> dict[str, Any]:
        session_state = self.request.session.get(self.session_key, {})
        if not isinstance(session_state, dict):
            session_state = {}
            self.request.session[self.session_key] = session_state
            self.request.session.modified = True
        return session_state
    
    def _set_state(self, state: dict[str, Any]) -> None:
        self.request.session[self.session_key] = state
        self.request.session.modified = True
        
    def clear_state(self):
        """Clears the state of the wizard
        """
        if self.session_key in self.request.session:
            self.request.session.pop(self.session_key)
            self.request.session.modified = True
    
    def set_session_data(self, key:str, value:Any) -> None:
        """Sets the session data

        Args:
            key (str): the key of the session
            value (Any): the value (must be json serializable)
        """
        state = self._get_state()
        state[key] = value
        self._set_state(state)
    
    def get_session_data(self, key:str) -> Any:
        """Retrieves session data based on the key

        Args:
            key (str): the key
            
        Returns:
            Any: the actual stored value
        """
        state = self._get_state()
        return state.get(key)
    
    def get_all_session_data(self) -> dict[str, Any]:
        return self._get_state().copy()
    
@dataclass
class WizardStep:
    name: str
    template_name: str
    description: str = ""
    context_func: Callable[[HttpRequest, Any, BaseStateOrchestrator], dict[str, Any]] | None = None
    process_func: Callable[[HttpRequest, Any, BaseStateOrchestrator], None] | None = None


@dataclass
class WizardError:
    message: str
    step: int | None = None
    title: str = ""
    

    
class WizardMixin:
    state_orchestrator_cls : Type[BaseStateOrchestrator] = BaseStateOrchestrator
    steps : list[WizardStep] = None
    template_name:str = "base_wizard.html"
    session_key:str = "default_session_key"
    step_query_param: str = "step"
    wizard_step_state_key: str = "__wizard_step"
    wizard_error_state_key: str = "__wizard_error"
    htmx_include_addendum = False

    def setup(self, request: HttpRequest, *args: Any, **kwargs: Any) -> None:
        super().setup(request, *args, **kwargs)
        self.orchestrator = self.state_orchestrator_cls(request=request, session_key=self.session_key)

        if request.GET.get("reset_wizard") == "true":
            self.clear_state()

    
    def clear_state(self):
        """Clears the state of the wizard
        """
        self.orchestrator.clear_state()

    def get_step(self, step: int) -> WizardStep | None:
        raise NotImplementedError("Implement get_step(step) or define steps list")

    def set_current_step_index(self, step: int) -> None:
        self.orchestrator.set_session_data(self.wizard_step_state_key, max(step, 0))

    def set_wizard_error(self, error: WizardError, fallback_step: int) -> None:
        step = error.step if error.step is not None else fallback_step
        self.orchestrator.set_session_data(
            self.wizard_error_state_key,
            {
                "step": max(step, 0),
                "message": str(error.message or ""),
                "title": str(error.title or ""),
            },
        )

    def clear_wizard_error(self) -> None:
        self.orchestrator.set_session_data(self.wizard_error_state_key, None)

    def get_wizard_error(self, step: int) -> WizardError | None:
        stored_error = self.orchestrator.get_session_data(self.wizard_error_state_key)
        if not isinstance(stored_error, dict):
            return None

        if stored_error.get("step") != step:
            return None

        message = str(stored_error.get("message") or "").strip()
        if not message:
            return None

        return WizardError(
            message=message,
            step=stored_error.get("step"),
            title=str(stored_error.get("title") or ""),
        )

    def get_current_step_index(self) -> int:
        if self.step_query_param in self.request.GET:
            step_value = self.request.GET.get(self.step_query_param, "0")
        else:
            step_value = str(self.orchestrator.get_session_data(self.wizard_step_state_key) or "0")

        try:
            step = int(step_value)
        except (TypeError, ValueError):
            step = 0

        step = self.normalize_step_index(max(step, 0))
        self.set_current_step_index(step)
        return step

    def normalize_step_index(self, step: int) -> int:
        """Normalize a requested step index before the wizard renders it.

        Subclasses can override this to enforce prerequisites for later steps.
        """
        return max(step, 0)

    def get_total_steps(self, max_steps: int = 20) -> int:
        if isinstance(self.steps, list):
            return len(self.steps)

        for index in range(max_steps):
            if self.get_wizard_step(index) is None:
                return index
        return max_steps

    def render_step(self, step: int, **kwargs: Any) -> HttpResponse:
        self.set_current_step_index(step)
        context = self.get_context_data(step=step, **kwargs)
        return self.render_to_response(context)

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        step = self.get_current_step_index()
        if self.get_wizard_step(step) is None:
            return self._handle_done()
        return self.render_step(step=step, **kwargs)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        step = self.get_current_step_index()
        current_step = self.get_wizard_step(step)

        if current_step is None:
            return self._handle_done()

        action = request.POST.get("_wizard_action", "next")
        if action == "back":
            self.clear_wizard_error()
            prev_step = max(step - 1, 0)
            return self.render_step(step=prev_step, **kwargs)

        if current_step.process_func:
            process_result = current_step.process_func(request, self, self.orchestrator)
            if isinstance(process_result, WizardError):
                self.set_wizard_error(process_result, fallback_step=step)
                return self.render_step(step=process_result.step if process_result.step is not None else step, **kwargs)

        self.clear_wizard_error()

        if not self.should_advance_after_process(step):
            return self.render_step(step=step, **kwargs)

        next_step = step + 1
        if self.get_wizard_step(next_step) is None:
            return self._handle_done(current_step=step)

        return self.render_step(step=next_step, **kwargs)

    def should_advance_after_process(self, step: int) -> bool:
        """Return whether a successful POST on the current step should advance.

        Subclasses can override this for steps that support internal actions such
        as pagination or preview refresh without moving to the next wizard step.
        """
        return True

    def _handle_done(self, current_step: int | None = None) -> HttpResponse:
        response = self.done()

        if isinstance(response, WizardError):
            error_step = response.step if response.step is not None else max(current_step or 0, 0)
            self.set_wizard_error(response, fallback_step=error_step)
            return self.render_step(step=error_step)

        self.clear_state()
        if isinstance(response, HttpResponse):
            return response
        return redirect(self.request.path)

    def done(self) -> HttpResponse | WizardError | None:
        raise NotImplementedError("Implement done() on WizardMixin subclass")
            
    def get_context_data(self, **kwargs) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        step_index = kwargs.pop("step", self.get_current_step_index())
        step = self.get_wizard_step(step_index)
        step_context: dict[str, Any] = {}

        if step and step.context_func:
            step_context = step.context_func(self.request, self, self.orchestrator) or {}

        context.update(step_context)
        context["wizard_step"] = step
        context["step_index"] = step_index
        context["wizard_total_steps"] = self.get_total_steps()
        context["step_title"] = step.name if step else ""
        context["step_description"] = step.description if step else ""
        context["step_template_name"] = step.template_name if step else ""
        context["wizard_step_query_param"] = self.step_query_param
        context["wizard_error"] = self.get_wizard_error(step_index)
        context["wizard_has_data"] = self.wizard_has_data()
        return context
    
    def get_wizard_step(self, step:int) -> WizardStep | None:
        """Returns the steps of the wizard.
        If it returns none, it means that 
        """
        if step < 0:
            return None

        if self.steps is None:
            return self.get_step(step)
        
        if isinstance(self.steps, list):
            if len(self.steps) == 0:
                raise NotImplementedError("At least one step required when creating a wizard")

            if step >= len(self.steps):
                return None

            wizard_step = self.steps[step]

            if not isinstance(wizard_step, WizardStep):
                raise ValueError("Step needs to be of type wizard step")

            return wizard_step

        raise ValueError("steps needs to be a list[WizardStep] when provided")
            
    def wizard_has_data(self) -> bool:
        """Returns true if the wizard has any data in the session, false otherwise
        """
        state = self.orchestrator.get_all_session_data()
        state.pop(self.wizard_step_state_key, None)
        
        return bool(state)
    
        
