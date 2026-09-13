


from django.test import TestCase


class TestFilterParser(TestCase):
    
    def test_normal_condition(self):
        """
        UC: first_name=Kyle
        
        Expected Result: the filter should work be parsed
        """
        expression = ""
        
    
    def test_or_condition(self):
        """
        UC: (first_name=Kyle OR first_name=Brandon)
        
        Expected Result: criteria
        """
        
        #1. step_1
        
    def test_multiple_conditions(self):
        """
        UC: (first_name=David OR first_name=Kyle) AND (company=ABC OR company=XYZ)
        
        Expected Result: criteria
        """
        
        #1. step_1