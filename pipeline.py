import re
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

class CandidateTransformer:
    """
    Manages candidate data ingestion, deterministic deduplication and conflict resolution,
    provenance tracking, and runtime schema projection.
    """
    
    # Precedence ranking: Higher is more authoritative.
    SOURCE_PRECEDENCE = {
        "unstructured_note": 1,
        "recruiter_csv": 2
    }
    
    def __init__(self):
        # Canonical internal state
        self.canonical_record = {
            "full_name": None,
            "emails": [],      # List of unique, normalized emails
            "phones": [],      # List of unique, cleaned phone numbers
            "locations": [],   # List of dicts: {"city": ..., "country_code": ...}
            "skills": [],      # List of dicts: {"name": ..., "years_of_experience": ...}
            "experience": []   # List of dicts: {"company": ..., "role": ..., "start_date": ..., "end_date": ...}
        }
        
        # Provenance tracking log
        self.provenance: List[Dict[str, Any]] = []
        
        # Overall confidence score
        self.overall_confidence: float = 0.0
        
        # Internal metadata for source tracking and sorting
        self._field_sources: Dict[str, str] = {}           # field_name -> source_name
        self._email_metadata: Dict[str, Dict[str, Any]] = {} # email -> {"source": ..., "timestamp": ...}
        self._phone_metadata: Dict[str, Dict[str, Any]] = {} # phone -> {"source": ..., "timestamp": ...}
        self._location_metadata: Dict[str, Dict[str, Any]] = {} # city_countrycode -> {"source": ..., "timestamp": ...}
        self._skill_metadata: Dict[str, Dict[str, Any]] = {} # skill_name_lower -> {"sources": [...], "confidences": {...}, "timestamp": ...}
        self._experience_metadata: Dict[Tuple[str, str], Dict[str, Any]] = {} # (company_lower, role_lower) -> {"source": ..., "timestamp": ...}
        self._source_contributions: Dict[str, float] = {}   # source_name -> confidence_score

    def _get_precedence(self, source: str) -> int:
        return self.SOURCE_PRECEDENCE.get(source, 0)

    def _update_scalar_field(self, field: str, value: Any, source: str, method: str, timestamp: str):
        current_source = self._field_sources.get(field)
        if current_source is None or self._get_precedence(source) >= self._get_precedence(current_source):
            self.canonical_record[field] = value
            self._field_sources[field] = source
            
            # Log provenance
            self.provenance.append({
                "field": field,
                "value": value,
                "source": source,
                "method": method,
                "timestamp": timestamp
            })

    def _add_email(self, email: str, source: str, method: str, timestamp: str):
        email_clean = email.strip().lower()
        if not email_clean:
            return
            
        current_meta = self._email_metadata.get(email_clean)
        
        if email_clean not in self.canonical_record["emails"]:
            self.canonical_record["emails"].append(email_clean)
            self._email_metadata[email_clean] = {
                "source": source,
                "timestamp": timestamp
            }
            self.provenance.append({
                "field": "emails",
                "value": email_clean,
                "source": source,
                "method": method,
                "timestamp": timestamp
            })
        else:
            # Overwrite metadata/provenance if new source has higher precedence
            if current_meta and self._get_precedence(source) > self._get_precedence(current_meta["source"]):
                self._email_metadata[email_clean] = {
                    "source": source,
                    "timestamp": timestamp
                }
                self.provenance.append({
                    "field": "emails",
                    "value": email_clean,
                    "source": source,
                    "method": f"{method}_update_priority",
                    "timestamp": timestamp
                })

    def _add_phone(self, phone: str, source: str, method: str, timestamp: str):
        phone_clean = phone.strip()
        if not phone_clean:
            return
            
        current_meta = self._phone_metadata.get(phone_clean)
        
        if phone_clean not in self.canonical_record["phones"]:
            self.canonical_record["phones"].append(phone_clean)
            self._phone_metadata[phone_clean] = {
                "source": source,
                "timestamp": timestamp
            }
            self.provenance.append({
                "field": "phones",
                "value": phone_clean,
                "source": source,
                "method": method,
                "timestamp": timestamp
            })
        else:
            # Overwrite metadata if new source has higher precedence
            if current_meta and self._get_precedence(source) > self._get_precedence(current_meta["source"]):
                self._phone_metadata[phone_clean] = {
                    "source": source,
                    "timestamp": timestamp
                }
                self.provenance.append({
                    "field": "phones",
                    "value": phone_clean,
                    "source": source,
                    "method": f"{method}_update_priority",
                    "timestamp": timestamp
                })

    def _add_location(self, loc: dict, source: str, method: str, timestamp: str):
        city = loc.get("city")
        country_code = loc.get("country_code")
        
        if country_code:
            country_code = country_code.strip().upper()
        if city:
            city = city.strip()
            
        if not city and not country_code:
            return
            
        loc_key = f"{city or ''}_{country_code or ''}".lower()
        
        # Check if already exists in locations list
        found_idx = -1
        for idx, existing in enumerate(self.canonical_record["locations"]):
            exist_city = existing.get("city")
            exist_country = existing.get("country_code")
            
            city_match = (city or "").lower() == (exist_city or "").lower()
            country_match = (country_code or "").lower() == (exist_country or "").lower()
            
            if city_match and country_match:
                found_idx = idx
                break
                
        loc_obj = {"city": city, "country_code": country_code}
        
        if found_idx == -1:
            self.canonical_record["locations"].append(loc_obj)
            self._location_metadata[loc_key] = {
                "source": source,
                "timestamp": timestamp
            }
            self.provenance.append({
                "field": "locations",
                "value": loc_obj,
                "source": source,
                "method": method,
                "timestamp": timestamp
            })
        else:
            meta = self._location_metadata.get(loc_key, {})
            existing_source = meta.get("source")
            if existing_source is None or self._get_precedence(source) > self._get_precedence(existing_source):
                self._location_metadata[loc_key] = {
                    "source": source,
                    "timestamp": timestamp
                }
                self.canonical_record["locations"][found_idx] = loc_obj
                self.provenance.append({
                    "field": "locations",
                    "value": loc_obj,
                    "source": source,
                    "method": f"{method}_update_priority",
                    "timestamp": timestamp
                })

    def _add_or_update_skill(self, skill: dict, source: str, method: str, timestamp: str):
        name = skill.get("name")
        if not name:
            return
        name_clean = name.strip()
        name_lower = name_clean.lower()
        
        years = skill.get("years_of_experience")
        if years is not None:
            try:
                years = float(years)
            except ValueError:
                years = None
                
        found_idx = -1
        for idx, existing in enumerate(self.canonical_record["skills"]):
            if existing["name"].lower() == name_lower:
                found_idx = idx
                break
                
        skill_obj = {"name": name_clean, "years_of_experience": years}
        source_conf = self._source_contributions.get(source, 1.0)
        
        if found_idx == -1:
            self.canonical_record["skills"].append(skill_obj)
            self._skill_metadata[name_lower] = {
                "sources": [source],
                "confidences": {source: source_conf},
                "timestamp": timestamp
            }
            self.provenance.append({
                "field": f"skills.{name_clean}",
                "value": skill_obj,
                "source": source,
                "method": method,
                "timestamp": timestamp
            })
        else:
            meta = self._skill_metadata.get(name_lower, {})
            if "sources" not in meta:
                meta["sources"] = []
            if "confidences" not in meta:
                meta["confidences"] = {}
                
            if source not in meta["sources"]:
                meta["sources"].append(source)
            meta["confidences"][source] = source_conf
            meta["timestamp"] = timestamp
            
            # Decide on precedence for updating canonical record (highest precedence source wins)
            highest_other_precedence = max([self._get_precedence(s) for s in meta["sources"] if s != source], default=0)
            
            if self._get_precedence(source) >= highest_other_precedence:
                existing_skill = self.canonical_record["skills"][found_idx]
                if years is not None or existing_skill.get("years_of_experience") is None:
                    existing_skill["years_of_experience"] = years
                
                self.provenance.append({
                    "field": f"skills.{name_clean}",
                    "value": existing_skill,
                    "source": source,
                    "method": f"{method}_update",
                    "timestamp": timestamp
                })

    def _add_or_update_experience(self, exp: dict, source: str, method: str, timestamp: str):
        company = exp.get("company")
        if not company:
            return
        company_clean = company.strip()
        company_lower = company_clean.lower()
        
        role = exp.get("role")
        role_clean = role.strip() if role else None
        role_lower = role_clean.lower() if role_clean else ""
        
        key = (company_lower, role_lower)
        
        start_date = exp.get("start_date")
        end_date = exp.get("end_date")
        
        start_date = start_date.strip() if start_date else None
        end_date = end_date.strip() if end_date else None
        
        found_idx = -1
        for idx, existing in enumerate(self.canonical_record["experience"]):
            exist_comp = existing.get("company", "").lower()
            exist_role = existing.get("role", "").lower() if existing.get("role") else ""
            if exist_comp == company_lower and exist_role == role_lower:
                found_idx = idx
                break
                
        exp_obj = {
            "company": company_clean,
            "role": role_clean,
            "start_date": start_date,
            "end_date": end_date
        }
        
        if found_idx == -1:
            self.canonical_record["experience"].append(exp_obj)
            self._experience_metadata[key] = {
                "source": source,
                "timestamp": timestamp
            }
            self.provenance.append({
                "field": f"experience.{company_clean}",
                "value": exp_obj,
                "source": source,
                "method": method,
                "timestamp": timestamp
            })
        else:
            meta = self._experience_metadata.get(key, {})
            existing_source = meta.get("source")
            if existing_source is None or self._get_precedence(source) >= self._get_precedence(existing_source):
                existing_exp = self.canonical_record["experience"][found_idx]
                if start_date:
                    existing_exp["start_date"] = start_date
                if end_date:
                    existing_exp["end_date"] = end_date
                if role_clean:
                    existing_exp["role"] = role_clean
                    
                self._experience_metadata[key] = {
                    "source": source,
                    "timestamp": timestamp
                }
                self.provenance.append({
                    "field": f"experience.{company_clean}",
                    "value": existing_exp,
                    "source": source,
                    "method": f"{method}_update",
                    "timestamp": timestamp
                })

    def _update_overall_confidence(self):
        # We calculate overall confidence based on the highest precedence source that contributed
        # recruiter_csv confidence is 1.0. unstructured_note confidence is parsed from LLM.
        if "recruiter_csv" in self._source_contributions:
            self.overall_confidence = 1.0
        elif "unstructured_note" in self._source_contributions:
            self.overall_confidence = self._source_contributions["unstructured_note"]
        else:
            self.overall_confidence = 0.0

    def ingest_parsed_json(self, parsed_data: dict):
        """
        Ingests structured JSON data (usually from LLM extraction of unstructured notes).
        """
        source = "unstructured_note"
        method = "llm_extraction"
        timestamp = datetime.now().isoformat()
        
        if not parsed_data:
            return
            
        conf = parsed_data.get("overall_confidence", 0.0)
        self._source_contributions[source] = float(conf)
        
        # 1. Full Name
        if parsed_data.get("full_name"):
            self._update_scalar_field("full_name", parsed_data["full_name"], source, method, timestamp)
            
        # 2. Emails
        for email in parsed_data.get("emails", []):
            if email:
                self._add_email(email, source, method, timestamp)
                
        # 3. Phones
        for phone in parsed_data.get("phones", []):
            if phone:
                self._add_phone(phone, source, method, timestamp)
                
        # 4. Locations
        for loc in parsed_data.get("locations", []):
            if loc:
                self._add_location(loc, source, method, timestamp)
                
        # 5. Skills
        for skill in parsed_data.get("skills", []):
            if skill and skill.get("name"):
                self._add_or_update_skill(skill, source, method, timestamp)
                
        # 6. Experience
        for exp in parsed_data.get("experience", []):
            if exp and exp.get("company"):
                self._add_or_update_experience(exp, source, method, timestamp)
                
        self._update_overall_confidence()

    def ingest_csv_row(self, row: dict):
        """
        Ingests a dictionary representing a row from a recruiter CSV.
        """
        source = "recruiter_csv"
        method = "direct_mapping"
        timestamp = datetime.now().isoformat()
        
        self._source_contributions[source] = 1.0
        
        # 1. Full Name
        name_keys = ["full_name", "name", "Name", "Full Name", "Candidate Name"]
        full_name = None
        for k in name_keys:
            if k in row and row[k]:
                full_name = str(row[k]).strip()
                break
        if full_name:
            self._update_scalar_field("full_name", full_name, source, method, timestamp)
            
        # 2. Emails
        email_keys = ["email", "emails", "Email", "Emails", "Email Address"]
        emails_str = None
        for k in email_keys:
            if k in row and row[k]:
                emails_str = str(row[k]).strip()
                break
        if emails_str:
            emails = [e.strip().lower() for e in emails_str.replace(";", ",").split(",") if e.strip()]
            for email in emails:
                self._add_email(email, source, method, timestamp)
                
        # 3. Phones
        phone_keys = ["phone", "phones", "Phone", "Phones", "Phone Number", "Mobile"]
        phones_str = None
        for k in phone_keys:
            if k in row and row[k]:
                phones_str = str(row[k]).strip()
                break
        if phones_str:
            phones = [p.strip() for p in phones_str.replace(";", ",").split(",") if p.strip()]
            for phone in phones:
                self._add_phone(phone, source, method, timestamp)
                
        # 4. Location
        city_keys = ["city", "City", "town", "Town"]
        country_keys = ["country", "Country", "country_code", "Country Code", "CountryCode"]
        city = None
        for k in city_keys:
            if k in row and row[k]:
                city = str(row[k]).strip()
                break
        country = None
        for k in country_keys:
            if k in row and row[k]:
                country = str(row[k]).strip()
                break
        if city or country:
            location = {"city": city, "country_code": country.upper() if country else None}
            self._add_location(location, source, method, timestamp)
            
        # 5. Skills
        skill_keys = ["skills", "Skills", "Key Skills"]
        skills_str = None
        for k in skill_keys:
            if k in row and row[k]:
                skills_str = str(row[k]).strip()
                break
        if skills_str:
            parts = [s.strip() for s in skills_str.split(",") if s.strip()]
            for part in parts:
                if ":" in part:
                    s_name, s_exp = part.rsplit(":", 1)
                    s_name = s_name.strip()
                    try:
                        s_exp = float(s_exp.strip())
                    except ValueError:
                        s_exp = None
                else:
                    s_name = part
                    s_exp = None
                self._add_or_update_skill({"name": s_name, "years_of_experience": s_exp}, source, method, timestamp)
                
        # 6. Experience
        comp_keys = ["company", "Company", "Employer"]
        role_keys = ["role", "Role", "job_title", "Job Title", "Title"]
        start_keys = ["start_date", "Start Date", "StartDate"]
        end_keys = ["end_date", "End Date", "EndDate"]
        
        company = None
        for k in comp_keys:
            if k in row and row[k]:
                company = str(row[k]).strip()
                break
        role = None
        for k in role_keys:
            if k in row and row[k]:
                role = str(row[k]).strip()
                break
        start_date = None
        for k in start_keys:
            if k in row and row[k]:
                start_date = str(row[k]).strip()
                break
        end_date = None
        for k in end_keys:
            if k in row and row[k]:
                end_date = str(row[k]).strip()
                break
                
        if company:
            exp = {
                "company": company,
                "role": role,
                "start_date": start_date,
                "end_date": end_date
            }
            self._add_or_update_experience(exp, source, method, timestamp)
            
        self._update_overall_confidence()

    def _get_sorted_emails(self) -> List[str]:
        def sort_key(email):
            meta = self._email_metadata.get(email, {})
            source = meta.get("source", "unstructured_note")
            source_priority = self._get_precedence(source)
            timestamp = meta.get("timestamp", "")
            return (-source_priority, timestamp)
        return sorted(self.canonical_record["emails"], key=sort_key)

    def _get_sorted_phones(self) -> List[str]:
        def sort_key(phone):
            meta = self._phone_metadata.get(phone, {})
            source = meta.get("source", "unstructured_note")
            source_priority = self._get_precedence(source)
            timestamp = meta.get("timestamp", "")
            return (-source_priority, timestamp)
        return sorted(self.canonical_record["phones"], key=sort_key)

    def _get_sorted_locations(self) -> List[Dict[str, Any]]:
        def sort_key(loc):
            city = loc.get("city") or ""
            country = loc.get("country_code") or ""
            loc_key = f"{city}_{country}".lower()
            meta = self._location_metadata.get(loc_key, {})
            source = meta.get("source", "unstructured_note")
            source_priority = self._get_precedence(source)
            timestamp = meta.get("timestamp", "")
            return (-source_priority, timestamp)
        return sorted(self.canonical_record["locations"], key=sort_key)

    def _resolve_path(self, path: str) -> Tuple[Any, bool]:
        """
        Resolves a dot-notated/bracketed path string against the candidate data root.
        """
        if path == "overall_confidence":
            return self.overall_confidence, True
        if path == "provenance":
            return self.provenance, True
            
        # Build projected skills with confidence and sources list
        projected_skills = []
        for skill in self.canonical_record["skills"]:
            name_clean = skill["name"]
            name_lower = name_clean.lower()
            meta = self._skill_metadata.get(name_lower, {})
            
            sources = meta.get("sources", [])
            sorted_sources = sorted(sources, key=lambda s: self._get_precedence(s), reverse=True)
            
            confidences = meta.get("confidences", {})
            confidence = max([confidences.get(s, 1.0) for s in sorted_sources], default=1.0)
            
            projected_skills.append({
                "name": name_clean,
                "confidence": confidence,
                "sources": sorted_sources
            })
            
        data_root = {
            "full_name": self.canonical_record["full_name"],
            "emails": self._get_sorted_emails(),
            "phones": self._get_sorted_phones(),
            "locations": self._get_sorted_locations(),
            "skills": projected_skills,
            "experience": self.canonical_record["experience"]
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
        Filters, reshapes and maps the internal candidate record based on a config.
        Supports both dict-based field config and list-based field config.
        """
        try:
            config = json.loads(runtime_config_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid runtime configuration JSON: {e}") from e
            
        fields_config = config.get("fields", {})
        output = {}
        
        # Determine global default for on_missing
        global_on_missing = config.get("on_missing", "null")
        
        if isinstance(fields_config, dict):
            # Dict-based config format (our unit tests use this)
            for out_key, field_cfg in fields_config.items():
                path = field_cfg.get("path")
                required = field_cfg.get("required", False)
                on_missing = field_cfg.get("on_missing", global_on_missing)
                
                if not path:
                    raise ValueError(f"Path is missing for output field '{out_key}' in configuration.")
                    
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
                    output[out_key] = value
                    
        elif isinstance(fields_config, list):
            # List-based config format (requested by user)
            for field_cfg in fields_config:
                path_key = field_cfg.get("path")
                if not path_key:
                    raise ValueError("Field configuration missing 'path' property.")
                    
                from_key = field_cfg.get("from")
                
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
                    output[out_key] = value
                    
            # Handle root-level 'include_confidence'
            if config.get("include_confidence", False):
                output["confidence"] = self.overall_confidence
        else:
            raise ValueError("Configuration 'fields' must be a dictionary or a list.")
            
        return output
