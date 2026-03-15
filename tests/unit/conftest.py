"""Unit test fixtures and shared helpers.

Note on make_node helpers: both test_decompose_unit.py and test_summarize_unit.py
define local make_node() helpers with different signatures and defaults (different
parameters, different HierarchyOrigin values, different confidence scores). These
are intentionally NOT unified here because forcing a single signature would either
break callers or add complexity for no gain.

Similarly, make_gateway() appears in both test_decompose_unit.py and
test_summarize_unit.py with identical signatures but is kept local because each
test module pairs it with a module-specific ProviderAdapter stub.
"""

from __future__ import annotations
