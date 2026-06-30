import unittest
import json
from pipeline import CandidateTransformer

class TestCandidateTransformer(unittest.TestCase):
    
    def test_conflict_resolution(self):
        """
        Test 1: Verifies that deterministic merging prioritizes primary source data (recruiter_csv, rank 2)
        over secondary sources (unstructured_note, rank 1) when fields conflict.
        """
        transformer = CandidateTransformer()
        
        # 1. Ingest from unstructured note (lower priority)
        unstructured_data = {
            "full_name": "John Doe (Unstructured)",
            "emails": ["john.doe@unstructured.com"],
            "phones": ["+15550000000"],
            "skills": [
                {"name": "Python", "years_of_experience": 2}
            ],
            "overall_confidence": 0.8
        }
        transformer.ingest_parsed_json(unstructured_data)
        
        # 2. Ingest from recruiter CSV (higher priority)
        csv_row = {
            "full_name": "Johnathan Doe",
            "email": "john.doe@primary.com",
            "phone": "+15551111111",
            "skills": "Python:5, SQL:3"
        }
        transformer.ingest_csv_row(csv_row)
        
        # Test full name override (scalar field conflict resolution)
        self.assertEqual(transformer.canonical_record["full_name"], "Johnathan Doe")
        
        # Test emails priority sorting (CSV email at index 0 because recruiter_csv priority > unstructured_note)
        sorted_emails = transformer._get_sorted_emails()
        self.assertEqual(sorted_emails[0], "john.doe@primary.com")
        self.assertEqual(sorted_emails[1], "john.doe@unstructured.com")
        
        # Test skills merge and priority override
        python_skill = next(s for s in transformer.canonical_record["skills"] if s["name"] == "Python")
        self.assertEqual(python_skill["years_of_experience"], 5.0)  # Overwritten from 2 to 5 by CSV
        
        # SQL skill was added since it did not exist in unstructured notes
        sql_skill = next(s for s in transformer.canonical_record["skills"] if s["name"] == "SQL")
        self.assertEqual(sql_skill["years_of_experience"], 3.0)

    def test_projection_omit(self):
        """
        Test 2: Verifies that the projection layer successfully drops keys when `on_missing` is set to "omit".
        """
        transformer = CandidateTransformer()
        
        # Ingest minimal candidate data (no phones, no locations)
        unstructured_data = {
            "full_name": "Jane Smith",
            "emails": ["jane.smith@example.com"],
            "overall_confidence": 0.9
        }
        transformer.ingest_parsed_json(unstructured_data)
        
        # Configuration mapping phones[0] and locations[0].city with "omit"
        config = {
            "fields": {
                "name": {"path": "full_name", "required": True, "on_missing": "error"},
                "primary_email": {"path": "emails[0]", "required": True, "on_missing": "error"},
                "phone": {"path": "phones[0]", "required": False, "on_missing": "omit"},
                "city": {"path": "locations[0].city", "required": False, "on_missing": "omit"}
            }
        }
        
        output = transformer.project_output(json.dumps(config))
        
        # Keys "name" and "primary_email" must exist
        self.assertIn("name", output)
        self.assertEqual(output["name"], "Jane Smith")
        self.assertEqual(output["primary_email"], "jane.smith@example.com")
        
        # Keys "phone" and "city" must be completely omitted from output
        self.assertNotIn("phone", output)
        self.assertNotIn("city", output)

    def test_projection_error(self):
        """
        Test 3: Verifies that the projection layer correctly throws a ValueError
        when a field is missing and `on_missing` is set to "error".
        """
        transformer = CandidateTransformer()
        
        # Ingest candidate data missing emails
        unstructured_data = {
            "full_name": "Bob Miller",
            "overall_confidence": 0.95
        }
        transformer.ingest_parsed_json(unstructured_data)
        
        # Configuration requiring emails[0] with on_missing set to "error"
        config = {
            "fields": {
                "name": {"path": "full_name", "required": True, "on_missing": "error"},
                "primary_email": {"path": "emails[0]", "required": True, "on_missing": "error"}
            }
        }
        
        with self.assertRaises(ValueError) as context:
            transformer.project_output(json.dumps(config))
            
        self.assertIn("primary_email", str(context.exception))

if __name__ == "__main__":
    unittest.main()
