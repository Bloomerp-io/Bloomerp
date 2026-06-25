# BloomERP Router
The BloomERP Router is one of the core functionalities that lets you easily integrate your own custom code inside of the app's UI, without having to go through the process of configuring things.

The goal is to make sure any custom views, beyond everything provided by core BloomERP, will be neatly integrated into the UI.

## Getting started
In order to get started, you'll have to go into settings and declare in which views you are using a BloomERP router. That way, the app will pick up where to find custom routers.

```python
# in settings.py

BLOOMERP_ROUTERS = [
    "employees.views.router" # app.view_file.variable_name_of_router
]

```

## Custom detail views
One common concern that has to be dealt with, is being able to write custom detail views that fit into the UI.

Say for instance we have an Employee model. Beyond the out of the box views that BloomERP generates (CRUD, foreign-key relationships, ...), we might want to add a custom detail view that let's you send an email to a specific user.

We would like to integrate this view in the UI so that we can access it whenever we navigate to a specific employee. For this, we can use the BloomERP router

```python
# In views.py 
from bloomerp.utils import BloomerpRouter
from bloomerp.models.mixins import BloomerpContextModelMixin as Context
from .models import Employee

# Initialize the router
router = BloomerpRouter()

# 
@router.detail_view_route(
    model = Employee,
    append_url = 'send-email',
    name = 'Send email',
    description = 'Send an email to a particular employee'
)
class EmployeeSendEmailView(Context, DetailView):
    template_name = ...
    model = Employee


```
Let's now also add the template.
```html
{% extends views/generic/detail/overview.html %}

```


The above example will do two things:
1. Add the following URL pattern /employees/(pk)/send-email/ to the application
2. Make it accessible as a tab so that the user can easily access it in the detail view

INSERT IMAGE 

### Detail view routes for multiple models
There might be situations in which we want to re-use a particular detail view for multiple models. Let's therefore imagine a the following situation in which we want 

```python
# ...
from .models import Employee, Client, Lead
@router.detail_view_route(
    model = [Employee, Client, Lead],
    append_url = 'send-email',
    name = 'Send email',
    description = 'Send an email to a particular employee'
)
class EmailSendView(Context, DetailView):
    model = None # model will be dynamically given on the backend based on the models defined in the backed

    def post(self, ...):
        subject = request.POST.get('subject')
        content = request.POST.get('email')
        email = self.get_object().email

        # optionally do some conditional statements based on the given model

        if email:
            send_email(email, subject, content)

```
The below example will create the following routes:
- /employees/pk/send-email/
- /clients/pk/send-email/
- /leads/pk/send-email/

## Custom list view routers
Additionally, you might want to add custom functionality for a particular model on a list/model level. In this case, the route will not be added on a detail view level, but rather on the level of the model.

An example would be creating a view that routes to the following destination:

/employees/generate-custom-report/

This particular route should be linked to a view in which we can generate a custom report.

```python
# in employees/views.py
from bloomerp.utils import BloomerpRouter
from .models import Employee

# initialize the router
router = BloomerpRouter()

# Some view

```

## Nested detail view routes
We might also come accross a situation in which we would like to create nested detail views. An example of a nested detail view url is the following

/employees/pk/document-templates/

