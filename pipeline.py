import re
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

def normalize_e164(phone: str) -> str:
    if not phone:
        return phone
    cleaned = "".join([c for c in phone if c.isdigit() or c == '+'])
    if cleaned and not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned

def normalize_canonical(skill_name: str) -> str:
    if not skill_name:
        return skill_name
    return skill_name.strip().title()

class CandidateTransformer:
    """
    Manages candidate data ingestion, deterministic deduplication and conflict resolution,
    provenance tracking, and runtime schema projection conforming to the Eightfold specification.
    """
    
    # Precedence ranking: Higher is more authoritative.
    SOURCE_PRECEDENCE = {
        "unstructured_note": 1,
        "recruiter_csv": 2
    }
    
    def __init__(self):
        # Canonical internal state matching the target default output schema
        self.canonical_record = {
            "candidate_id": None,
            "full_name": None,
            "emails": [],
            "phones": [],
            "location": {
                "city": None,
                "region": None,
                "country": None
            },
            "links": {
                "linkedin": None,
                "github": None,
                "portfolio": None,
                "other": []
            },
            "headline": None,
            "years_experience": None,
            "skills": [],       # List of dicts: {"name": ..., "confidence": ..., "sources": [...]}
            "experience": [],   # List of dicts: {"company": ..., "title": ..., "start": ..., "end": ..., "summary": ...}
            "education": []     # List of dicts: {"institution": ..., "degree": ..., "field": ..., "end_year": ...}
        }
        
        # Provenance tracking log
        self.provenance: List[Dict[str, Any]] = []
        
        # Overall confidence score
        self.overall_confidence: float = 0.0
        
        # Internal metadata for source tracking
        self._field_sources: Dict[str, str] = {}             # field_path -> source_name
        self._email_metadata: Dict[str, Dict[str, Any]] = {}   # email -> {"source": ...}
        self._phone_metadata: Dict[str, Dict[str, Any]] = {}   # phone -> {"source": ...}
        self._source_contributions: Dict[str, float] = {}     # source_name -> confidence_score

    def _get_precedence(self, source: str) -> int:
        return self.SOURCE_PRECEDENCE.get(source, 0)

    def _log_provenance(self, field: str, source: str, method: str):
        log_entry = {"field": field, "source": source, "method": method}
        if log_entry not in self.provenance:
            self.provenance.append(log_entry)

    def _update_scalar(self, path: str, value: Any, source: str, method: str):
        if value is None:
            return
            
        current_source = self._field_sources.get(path)
        if current_source is None or self._get_precedence(source) >= self._get_precedence(current_source):
            # Traverses and updates nested structures
            parts = path.split('.')
            curr = self.canonical_record
            for p in parts[:-1]:
                curr = curr[p]
            curr[parts[-1]] = value
            
            self._field_sources[path] = source
            self._log_provenance(path, source, method)

    def _add_email(self, email: str, source: str, method: str):
        email_clean = email.strip().lower()
        if not email_clean:
            return
            
        current_meta = self._email_metadata.get(email_clean)
        
        if email_clean not in self.canonical_record["emails"]:
            self.canonical_record["emails"].append(email_clean)
            self._email_metadata[email_clean] = {"source": source}
            self._log_provenance("emails", source, method)
        else:
            if current_meta and self._get_precedence(source) > self._get_precedence(current_meta["source"]):
                self._email_metadata[email_clean] = {"source": source}
                self._log_provenance("emails", source, f"{method}_update_priority")

    def _add_phone(self, phone: str, source: str, method: str):
        phone_clean = phone.strip()
        if not phone_clean:
            return
            
        current_meta = self._phone_metadata.get(phone_clean)
        
        if phone_clean not in self.canonical_record["phones"]:
            self.canonical_record["phones"].append(phone_clean)
            self._phone_metadata[phone_clean] = {"source": source}
            self._log_provenance("phones", source, method)
        else:
            if current_meta and self._get_precedence(source) > self._get_precedence(current_meta["source"]):
                self._phone_metadata[phone_clean] = {"source": source}
                self._log_provenance("phones", source, f"{method}_update_priority")

    def _add_or_update_skill(self, skill: dict, source: str, method: str):
        name = skill.get("name")
        if not name:
            return
        name_clean = name.strip()
        name_lower = name_clean.lower()
        
        source_conf = float(skill.get("confidence") or self._source_contributions.get(source, 1.0))
        
        found_skill = None
        for s in self.canonical_record["skills"]:
            if s["name"].lower() == name_lower:
                found_skill = s
                break
                
        if not found_skill:
            new_skill = {
                "name": name_clean,
                "confidence": source_conf,
                "sources": [source]
            }
            self.canonical_record["skills"].append(new_skill)
            self._log_provenance(f"skills.{name_clean}", source, method)
        else:
            if source not in found_skill["sources"]:
                found_skill["sources"].append(source)
            found_skill["confidence"] = max(found_skill["confidence"], source_conf)
            self._log_provenance(f"skills.{name_clean}", source, f"{method}_update")

    def _add_or_update_experience(self, exp: dict, source: str, method: str):
        company = exp.get("company")
        if not company:
            return
        company_clean = company.strip()
        company_lower = company_clean.lower()
        
        title = exp.get("title") or exp.get("role")
        title_clean = title.strip() if title else None
        title_lower = title_clean.lower() if title_clean else ""
        
        start = exp.get("start") or exp.get("start_date")
        end = exp.get("end") or exp.get("end_date")
        summary = exp.get("summary")
        
        start = start.strip() if start else None
        end = end.strip() if end else None
        summary = summary.strip() if summary else None
        
        found_exp = None
        for e in self.canonical_record["experience"]:
            exist_comp = e.get("company", "").lower()
            exist_title = e.get("title", "").lower() if e.get("title") else ""
            if exist_comp == company_lower and exist_title == title_lower:
                found_exp = e
                break
                
        exp_obj = {
            "company": company_clean,
            "title": title_clean,
            "start": start,
            "end": end,
            "summary": summary
        }
        
        exp_key = f"experience.{company_lower}_{title_lower}"
        current_source = self._field_sources.get(exp_key)
        
        if not found_exp:
            self.canonical_record["experience"].append(exp_obj)
            self._field_sources[exp_key] = source
            self._log_provenance(f"experience.{company_clean}", source, method)
        else:
            if current_source is None or self._get_precedence(source) >= self._get_precedence(current_source):
                if start:
                    found_exp["start"] = start
                if end:
                    found_exp["end"] = end
                if summary:
                    found_exp["summary"] = summary
                if title_clean:
                    found_exp["title"] = title_clean
                    
                self._field_sources[exp_key] = source
                self._log_provenance(f"experience.{company_clean}", source, f"{method}_update")

    def _add_or_update_education(self, edu: dict, source: str, method: str):
        inst = edu.get("institution") or edu.get("school")
        if not inst:
            return
        inst_clean = inst.strip()
        inst_lower = inst_clean.lower()
        
        degree = edu.get("degree")
        field = edu.get("field") or edu.get("major")
        
        end_year = edu.get("end_year")
        if end_year is not None:
            try:
                end_year = int(end_year)
            except ValueError:
                end_year = None
                
        degree = degree.strip() if degree else None
        field = field.strip() if field else None
        
        found_edu = None
        for e in self.canonical_record["education"]:
            if e.get("institution", "").lower() == inst_lower:
                found_edu = e
                break
                
        edu_obj = {
            "institution": inst_clean,
            "degree": degree,
            "field": field,
            "end_year": end_year
        }
        
        edu_key = f"education.{inst_lower}"
        current_source = self._field_sources.get(edu_key)
        
        if not found_edu:
            self.canonical_record["education"].append(edu_obj)
            self._field_sources[edu_key] = source
            self._log_provenance(f"education.{inst_clean}", source, method)
        else:
            if current_source is None or self._get_precedence(source) >= self._get_precedence(current_source):
                if degree:
                    found_edu["degree"] = degree
                if field:
                    found_edu["field"] = field
                if end_year is not None:
                    found_edu["end_year"] = end_year
                    
                self._field_sources[edu_key] = source
                self._log_provenance(f"education.{inst_clean}", source, f"{method}_update")

    def _generate_candidate_id(self):
        if not self.canonical_record["candidate_id"]:
            self.canonical_record["candidate_id"] = "cand_" + str(uuid.uuid4())[:8]

    def _update_overall_confidence(self):
        if "recruiter_csv" in self._source_contributions:
            self.overall_confidence = 1.0
        elif "unstructured_note" in self._source_contributions:
            self.overall_confidence = self._source_contributions["unstructured_note"]
        else:
            self.overall_confidence = 0.0

    def ingest_parsed_json(self, parsed_data: dict):
        """
        Ingests structured JSON data conforming to the default output schema.
        """
        source = "unstructured_note"
        method = "llm_extraction"
        
        if not parsed_data:
            return
            
        conf = parsed_data.get("overall_confidence", 0.0)
        self._source_contributions[source] = float(conf)
        
        if parsed_data.get("candidate_id"):
            self._update_scalar("candidate_id", parsed_data["candidate_id"], source, method)
            
        if parsed_data.get("full_name"):
            self._update_scalar("full_name", parsed_data["full_name"], source, method)
            
        if parsed_data.get("headline"):
            self._update_scalar("headline", parsed_data["headline"], source, method)
            
        if parsed_data.get("years_experience") is not None:
            try:
                self._update_scalar("years_experience", float(parsed_data["years_experience"]), source, method)
            except ValueError:
                pass
                
        # Location subfields
        loc = parsed_data.get("location", {})
        if loc:
            if loc.get("city"):
                self._update_scalar("location.city", loc["city"], source, method)
            if loc.get("region"):
                self._update_scalar("location.region", loc["region"], source, method)
            if loc.get("country"):
                self._update_scalar("location.country", loc["country"], source, method)
                
        # Links subfields
        links = parsed_data.get("links", {})
        if links:
            if links.get("linkedin"):
                self._update_scalar("links.linkedin", links["linkedin"], source, method)
            if links.get("github"):
                self._update_scalar("links.github", links["github"], source, method)
            if links.get("portfolio"):
                self._update_scalar("links.portfolio", links["portfolio"], source, method)
            for o in links.get("other", []):
                if o and o not in self.canonical_record["links"]["other"]:
                    self.canonical_record["links"]["other"].append(o)
                    self._log_provenance("links.other", source, method)
                    
        # Emails and Phones
        for email in parsed_data.get("emails", []):
            if email:
                self._add_email(email, source, method)
        for phone in parsed_data.get("phones", []):
            if phone:
                self._add_phone(phone, source, method)
                
        # Skills
        for skill in parsed_data.get("skills", []):
            if skill and skill.get("name"):
                self._add_or_update_skill(skill, source, method)
                
        # Experience
        for exp in parsed_data.get("experience", []):
            if exp and exp.get("company"):
                self._add_or_update_experience(exp, source, method)
                
        # Education
        for edu in parsed_data.get("education", []):
            if edu and edu.get("institution"):
                self._add_or_update_education(edu, source, method)
                
        self._update_overall_confidence()
        self._generate_candidate_id()

    def ingest_csv_row(self, row: dict):
        """
        Ingests a dictionary representing a row from a recruiter CSV (name, email, phone, current_company, title).
        """
        source = "recruiter_csv"
        method = "direct_mapping"
        
        self._source_contributions[source] = 1.0
        
        if row.get("candidate_id"):
            self._update_scalar("candidate_id", str(row["candidate_id"]).strip(), source, method)
            
        name_keys = ["name", "Name", "full_name", "Full Name", "Candidate Name"]
        for k in name_keys:
            if k in row and row[k]:
                self._update_scalar("full_name", str(row[k]).strip(), source, method)
                break
                
        email_keys = ["email", "emails", "Email", "Emails", "Email Address"]
        for k in email_keys:
            if k in row and row[k]:
                emails = [e.strip().lower() for e in str(row[k]).replace(";", ",").split(",") if e.strip()]
                for email in emails:
                    self._add_email(email, source, method)
                break
                
        phone_keys = ["phone", "phones", "Phone", "Phones", "Phone Number", "Mobile"]
        for k in phone_keys:
            if k in row and row[k]:
                phones = [p.strip() for p in str(row[k]).replace(";", ",").split(",") if p.strip()]
                for phone in phones:
                    self._add_phone(phone, source, method)
                break
                
        # current_company and title -> current experience
        comp_keys = ["current_company", "current_company_name", "Company", "company"]
        title_keys = ["title", "Title", "job_title", "Job Title", "role", "Role"]
        
        company = None
        for k in comp_keys:
            if k in row and row[k]:
                company = str(row[k]).strip()
                break
        title = None
        for k in title_keys:
            if k in row and row[k]:
                title = str(row[k]).strip()
                break
                
        if company:
            exp = {
                "company": company,
                "title": title,
                "start": None,
                "end": "Present",
                "summary": "Current position"
            }
            self._add_or_update_experience(exp, source, method)
            
        # Location
        city_keys = ["city", "City"]
        region_keys = ["region", "Region", "state", "State"]
        country_keys = ["country", "Country", "country_code", "CountryCode"]
        
        city = None
        for k in city_keys:
            if k in row and row[k]:
                city = str(row[k]).strip()
                break
        region = None
        for k in region_keys:
            if k in row and row[k]:
                region = str(row[k]).strip()
                break
        country = None
        for k in country_keys:
            if k in row and row[k]:
                country = str(row[k]).strip()
                break
                
        if city:
            self._update_scalar("location.city", city, source, method)
        if region:
            self._update_scalar("location.region", region, source, method)
        if country:
            self._update_scalar("location.country", country, source, method)
            
        # Skills
        skill_keys = ["skills", "Skills", "Key Skills"]
        for k in skill_keys:
            if k in row and row[k]:
                parts = [s.strip() for s in str(row[k]).split(",") if s.strip()]
                for part in parts:
                    if ":" in part:
                        s_name, s_exp = part.rsplit(":", 1)
                        s_name = s_name.strip()
                    else:
                        s_name = part
                    self._add_or_update_skill({"name": s_name}, source, method)
                break
                
        self._update_overall_confidence()
        self._generate_candidate_id()

    def _get_sorted_emails(self) -> List[str]:
        def sort_key(email):
            meta = self._email_metadata.get(email, {})
            source = meta.get("source", "unstructured_note")
            return -self._get_precedence(source)
        return sorted(self.canonical_record["emails"], key=sort_key)

    def _get_sorted_phones(self) -> List[str]:
        def sort_key(phone):
            meta = self._phone_metadata.get(phone, {})
            source = meta.get("source", "unstructured_note")
            return -self._get_precedence(source)
        return sorted(self.canonical_record["phones"], key=sort_key)

    def _resolve_path(self, path: str) -> Tuple[Any, bool]:
        if path == "overall_confidence":
            return self.overall_confidence, True
        if path == "provenance":
            return self.provenance, True
            
        # Check for list wildcards, e.g., 'skills[].name'
        if '[]' in path:
            base_path, sub_key = path.split('[].')
            base_val, found = self._resolve_path(base_path)
            if found and isinstance(base_val, list):
                list_vals = []
                for item in base_val:
                    if isinstance(item, dict) and sub_key in item:
                        list_vals.append(item[sub_key])
                return list_vals, True
            return None, False
            
        data_root = {
            "candidate_id": self.canonical_record["candidate_id"],
            "full_name": self.canonical_record["full_name"],
            "emails": self._get_sorted_emails(),
            "phones": self._get_sorted_phones(),
            "location": self.canonical_record["location"],
            "links": self.canonical_record["links"],
            "headline": self.canonical_record["headline"],
            "years_experience": self.canonical_record["years_experience"],
            "skills": self.canonical_record["skills"],
            "experience": self.canonical_record["experience"],
            "education": self.canonical_record["education"]
        }
        
        parts = path.split('.')
        current = data_root
        
        for part in parts:
            match = re.match(r'^(\w+)(?:\[(\d+)\])?$', part)
            if not match:
                return None, False
                
            key, index_str = match.groups()
            
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None, False
                
            if index_str is not None:
                index = int(index_str)
                if isinstance(current, list):
                    if 0 <= index < len(current):
                        current = current[index]
                    else:
                        return None, False
                else:
                    return None, False
                    
        return current, True

    def project_output(self, runtime_config_json: str) -> Dict[str, Any]:
        """
        Reshapes the canonical candidate profile based on a runtime layout specification.
        """
        try:
            config = json.loads(runtime_config_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid runtime configuration JSON: {e}") from e
            
        fields_config = config.get("fields", [])
        output = {}
        
        # Global on_missing behavior fallback
        global_on_missing = config.get("on_missing", "null")
        
        for field_cfg in fields_config:
            path_key = field_cfg.get("path")
            if not path_key:
                raise ValueError("Field configuration missing 'path' property.")
                
            from_key = field_cfg.get("from")
            
            # If 'from' is defined, output key is 'path' and internal path is 'from'.
            # If not defined, output key and internal path are both 'path'.
            if from_key:
                out_key = path_key
                path = from_key
            else:
                out_key = path_key
                path = path_key
                
            required = field_cfg.get("required", False)
            on_missing = field_cfg.get("on_missing", global_on_missing)
            
            value, found = self._resolve_path(path)
            is_missing = not found or value is None
            
            if is_missing:
                if required or on_missing == "error":
                    raise ValueError(f"Required field '{out_key}' (path: '{path}') is missing from candidate record.")
                elif on_missing == "omit":
                    continue
                elif on_missing == "null":
                    output[out_key] = None
                else:
                    raise ValueError(f"Unknown on_missing action '{on_missing}' for field '{out_key}'.")
            else:
                # Perform layout normalization
                norm_type = field_cfg.get("normalize")
                if norm_type:
                    if norm_type == "E164":
                        if isinstance(value, list):
                            value = [normalize_e164(v) for v in value]
                        elif isinstance(value, str):
                            value = normalize_e164(value)
                    elif norm_type == "canonical":
                        if isinstance(value, list):
                            value = [normalize_canonical(v) for v in value]
                        elif isinstance(value, str):
                            value = normalize_canonical(value)
                output[out_key] = value
                
        # Handle root-level 'include_confidence'
        if config.get("include_confidence", False):
            output["confidence"] = self.overall_confidence
            
        # Handle root-level 'include_provenance'
        if config.get("include_provenance", False):
            output["provenance"] = [
                {
                    "field": p["field"],
                    "source": p["source"],
                    "method": p["method"]
                }
                for p in self.provenance
            ]
            
        return output
