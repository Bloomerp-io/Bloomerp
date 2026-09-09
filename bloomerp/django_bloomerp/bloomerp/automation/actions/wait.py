import time

from numpy import tri

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.forms.base_workflow_node_form import BaseWorkflowNodeForm
from django import forms

class WaitForm(BaseWorkflowNodeForm):
    wait_time = forms.IntegerField(
        help_text="The time in seconds to wait"
    )


class WaitExecutor(BaseExecutor):
    config_form = WaitForm

    def execute(self, trigger_data):
        wait_time = self.resolve_config(trigger_data).get("wait_time", 0)
        time.sleep(wait_time)
        return trigger_data

    @classmethod
    def get_output_schema(cls, config=None, input_schema=None, port_id="default"):
        return input_schema
