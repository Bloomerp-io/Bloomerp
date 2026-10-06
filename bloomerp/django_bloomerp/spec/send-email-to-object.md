# Feature: Send email to object

This feature will:
- Enhance the email functionality
- Give users the ability to send emails using specific document templates
- Give users the ability to store email drafts and retrieve

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant F as Frontend
    participant B as Backend

    alt object has no email field
        U->>F: User doesn't see "Email" button
    end

    U->>F: Click email
    F-->U: Dropdown with email fields
    U->>F: Click email field (example, 'email')
    F->>B: HTMX: new_email?object_id=<object_id>&content_type_id=<content_type_id>
    B-->B: Search for document templates with content_type
    B-->B: Retrieve the email field of the object
    B-->B: Retrive the user's current email account
    B-->F: new_email component (with to_email filled in already, and a template selector)
    F-->F: Email editor component stores content type and object ID
    F-->U: Modal with content
    U-->U: User can select a different from account if necessary (based on access)
    U-->F: Select template
    F->>B: load_template(document_template_id) (from email_editor component)
    B-->F: template
    F-->U: template, with form args based on template vars (prefilled if possible)
    U->>F: Update some stuff from the template
    F->>B: Once something changes: create_email_draft(...) -> use SDK
    B-->F: draft id
    alt Email is sent
        U->>F: press "send email" button
        F-->U: Email send button loading animation
        F->>B: POST: new_email(content, email_account, doc_template_id, form args, [draft_id])
        B-->B: Resolve object ID's, 
        B-->F: Completed
        F-->U: Completed
    end
    

```

## Notes
- We want to re-use the send_email endpoint for this, so that this will also work from the regular inbox
- Content that is overriden in the editor should override the document template. The only reason I can think of that the doc template is needed in the send_email endpoint is to resolve the content types
- The EmailEditor.ts should remain the sending part
- The button should be in the sidebar of the detail view, next to create todo
  - If the object has no email field, button shouldn't show

## Extra changes

- We need to be able to store the selected/default email account for a user. This should be a one-to-one field to from user to email account. Permissions should apply
- There should be an option in the create email account wizard to set it as the default email account
  - This selection should be changable via profile view
- EmailDraft model: very light internal model to store email drafts
- 