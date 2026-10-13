from bloomerp.modules.definition import BloomerpModule

class FileManagement(BloomerpModule):
    """Expose agent management alongside usage and execution monitoring."""

    id = "files"
    code = "files"
    icon = "fa-solid fa-file"
    name = "File Management"
    description = "Manage your files."