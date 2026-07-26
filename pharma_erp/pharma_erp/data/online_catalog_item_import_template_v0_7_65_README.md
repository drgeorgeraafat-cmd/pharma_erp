# Online Catalog Item Import Template

This template is for the real catalogue after the Full Test Data Reset.

## Important rules

- `custom_online_category` must be an enabled leaf Online Category.
- `custom_show_online` should be `0` until the real product is reviewed.
- `custom_online_availability_status` accepts:
  - Available
  - Temporarily Unavailable
  - Coming Soon
  - Hidden
- `custom_search_keywords__aliases` is reused for both internal aliases and online search.
- Do not create a duplicate online-keywords field.
- `image` should contain the uploaded product-image URL.
- Items requiring a prescription must use `custom_requires_prescription = 1`.
- Use `Online Catalog Publishing Readiness` before publication.
