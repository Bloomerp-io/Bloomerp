from bloomerp.models import BloomerpModel

class Form(BloomerpModel):
    """
    A form is something that can be filled out by users to collect data.
    """
    class Meta:
        verbose_name = "Form"
        verbose_name_plural = "Forms"
        
    avatar = None
    
    