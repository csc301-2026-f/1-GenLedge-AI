---
id: repair
version: 1
variables:
  - validation_errors
  - output_schema
contract: ModelDraft
---
Your previous response did not match the required output contract.

## Validation errors

{{validation_errors}}

## Required schema

{{output_schema}}

Return a corrected single JSON object that satisfies the schema exactly. Do not
add commentary, do not wrap the object in prose, and do not repeat the invalid
response.
