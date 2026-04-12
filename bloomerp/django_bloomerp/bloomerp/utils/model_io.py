import pandas as pd
from django.core.files import File
from django.db import models
from io import BytesIO, StringIO, TextIOWrapper
import csv
import openpyxl
from django.core.exceptions import ValidationError

class BloomerpModelIO:
    def __init__(self, model: models.Model):
        self.model = model

    def get_model_fields(self) -> list[models.Field]:
        """
        Get all of the fields for the that are editable and not an AutoField.
        """
        fields = self.model._meta.get_fields()

        # Filter out fields that are not editable and id fields
        return [field for field in fields if field.editable and not isinstance(field, models.AutoField)]

    def get_model_fields_as_str(self) -> list[str]:
        """
        Get all of the fields for the model as a list of strings.
        """
        return [field.name for field in self.get_model_fields()]

    def get_model_field_data_types(self) -> dict:
        """
        Get the field names and their corresponding data types for the model.
        """
        return {field.name: field for field in self.get_model_fields()}

    def export_to_csv(self, queryset=None, fields='__all__') -> bytes:
        """
        Export the model data to a CSV file in bytes format.
        If the queryset is None, export all of the model data.
        """
        if queryset is None:
            queryset = self.model.objects.all()

        if fields == '__all__':
            fields = [field.name for field in self.get_model_fields()]

        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(fields)

        for obj in queryset:
            row = [getattr(obj, field) for field in fields]
            writer.writerow(row)

        csv_content = buffer.getvalue()
        buffer.close()

        return csv_content.encode('utf-8')  # Convert string to bytes

    def export_to_excel(self, queryset=None, fields='__all__') -> bytes:
        """
        Export the model data to an Excel file in bytes format.
        If the queryset is None, export all of the model data.
        """
        if queryset is None:
            queryset = self.model.objects.all()

        if fields == '__all__':
            fields = [field.name for field in self.get_model_fields()]

        buffer = BytesIO()
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(fields)

        for obj in queryset:
            row = [getattr(obj, field).__str__() for field in fields]
            sheet.append(row)

        workbook.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()

    def validate_row_data(self, row: dict, fields: dict) -> bool:
        """
        Validate a single row of data to check if it matches the field types of the model.
        """
        for field_name, field in fields.items():
            value = row.get(field_name, None)

            if value is None:
                if not field.null:
                    return False  # Non-nullable field is missing
            else:
                try:
                    # Perform type validation based on Django field type
                    if isinstance(field, (models.IntegerField, models.AutoField)):
                        int(value)  # Try to cast to int
                    elif isinstance(field, models.FloatField):
                        float(value)  # Try to cast to float
                    elif isinstance(field, models.BooleanField):
                        if not isinstance(value, bool):
                            return False  # Value must be boolean
                    elif isinstance(field, models.DateField):
                        pd.to_datetime(value, errors='raise')  # Validate date
                    elif isinstance(field, models.CharField):
                        str(value)  # Ensure it is string-like
                except (ValueError, TypeError):
                    return False  # Value does not match expected type

        return True

    def import_from_template(self, file: File) -> list[dict]:
        '''
        Imports data from a CSV or Excel file template and returns a list of dictionaries with data for objects.
        '''
        # Load the file into a pandas dataframe
        if file.name.endswith('.csv'):
            dataframe = pd.read_csv(TextIOWrapper(file.file, encoding='utf-8'))
        elif file.name.endswith('.xlsx'):
            dataframe = pd.read_excel(file)
        else:
            raise ValueError("Unsupported file type. Only CSV and Excel files are allowed.")
        
        # Give the dataframe to the template_is_valid method to check if the template is valid
        if not self._template_is_valid(dataframe):
            raise ValidationError("Invalid template. Please ensure all required fields are present.")
        

        # Fill NaN values with empty strings
        dataframe.fillna('', inplace=True)

        # Create a list of unsaved model instances
        instances = []
        for _, row in dataframe.iterrows():
            obj_data = {}
            m2m_fields = []
            for field in self.get_model_fields():
                field_name = field.name
                if field_name in row:
                    # Check if the field is a ManyToManyField, if so split the values by | and store them in a list
                    if isinstance(field, models.ManyToManyField):
                        if type(row[field_name]) == str:
                            obj_data[field_name] = row[field_name].split('|')
                        else:
                            # Only one value, so store it in a list
                            obj_data[field_name] = [row[field_name]]
                    else:
                        obj_data[field_name] = row[field_name]

            instances.append(obj_data)

        return instances

    def _template_is_valid(self, dataframe:pd.DataFrame) -> bool:
        # Get model fields as a list of strings, assuming they are comma-separated
        fields = self.get_model_fields_as_str()

        # Trim whitespace and convert columns to lowercase for consistent comparison
        df_columns = dataframe.columns.str.strip().str.lower()
        fields = [field.lower() for field in fields]

        print("File columns:", df_columns.tolist())
        print("Model fields:", fields)

        # Check if all of the model fields are present in the template (file columns)
        if not set(df_columns).issubset(fields):
            return False

        return True

    def create_model_template(self, file_type: str, fields='__all__') -> bytes:
        """
        Create a template for the model in the specified file format (CSV or Excel).

        Args:
            file_type (str): The file format to create the template in ('csv' or 'xlsx').
            fields (list): The fields to include in the template. If '__all__', include all fields.
        """
        # Validate fields
        model_fields = [field.name for field in self.get_model_fields()]
        if fields == '__all__':
            fields = model_fields
        else:
            # Ensure all provided fields are valid model fields
            invalid_fields = [field for field in fields if field not in model_fields]
            if invalid_fields:
                raise ValueError(f"Invalid fields: {', '.join(invalid_fields)}")

        if file_type == 'csv':
            buffer = StringIO()
            writer = csv.writer(buffer)
            writer.writerow(fields)
            csv_content = buffer.getvalue()
            buffer.close()
            return csv_content.encode('utf-8')  # Convert string to bytes

        elif file_type == 'xlsx':
            buffer = BytesIO()
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.append(fields)
            workbook.save(buffer)
            buffer.seek(0)
            return buffer.getvalue()

        else:
            raise ValueError("Invalid file type. Must be either 'csv' or 'xlsx'.")
        