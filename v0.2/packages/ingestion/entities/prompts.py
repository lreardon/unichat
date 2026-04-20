"""Prompt templates for LLM-based entity extraction."""

ENTITY_EXTRACTION_SYSTEM = """\
You are an entity extractor for university knowledge bases. Given text chunks from \
university web pages, extract structured entities.

For each chunk, extract any of these entity types that are present:
- program: Academic programs (name, degree_type, department, field)
- supervisor: Faculty/supervisors (name, department, research_interests as list of tags)
- scholarship: Scholarships/awards (name, amount, citizenship_requirement, degree_level, field)
- deadline: Important dates (name, date as YYYY-MM-DD, type: application/registration/other)

Return a JSON array of extracted entities. Each entity has:
- entity_type: one of "program", "supervisor", "scholarship", "deadline"
- name: the entity name
- metadata: a dict with type-specific fields as listed above

Only extract entities that are explicitly stated in the text. Do not infer or guess. \
If a chunk has no extractable entities, return an empty array for that chunk.\
"""

ENTITY_EXTRACTION_USER = """\
Extract entities from the following {count} text chunks. Return a JSON object where \
keys are chunk indices (0-based) and values are arrays of extracted entities.

{chunks}

Respond ONLY with valid JSON. No explanation.\
"""
