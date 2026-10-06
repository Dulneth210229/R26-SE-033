"""
Unit tests for schema_form_checker.py -- pure, tmp_path-only, no LLM/Docker/git, mirrors
test_coder_db_fallback_checker.py's established idiom.
"""

from app.agents.coder_agent.schema_form_checker import check_required_field_form_coverage

# Mirrors the exact real, reported bug: a custom `id` field required+unique that no form field
# ever sets.
BUGGY_MODEL = """\
import mongoose, { Schema } from "mongoose";

const schema = new Schema({
  id: { type: String, required: true, unique: true },
  name: { type: String, required: true },
  price: { type: Number, required: true },
  description: { type: String },
  createdAt: { type: Date, required: true, default: Date.now },
});

export default mongoose.models.Item || mongoose.model("Item", schema);
"""

BUGGY_FORM = """\
export default function ItemListingPage() {
  const [formData, setFormData] = useState({
    id: "",
    name: "",
    price: 0,
    description: "",
  });

  return (
    <form>
      <input name="name" value={formData.name} />
      <input name="price" value={formData.price} />
      <input name="description" value={formData.description} />
    </form>
  );
}
"""

FIXED_FORM = """\
export default function ItemListingPage() {
  const [formData, setFormData] = useState({
    name: "",
    price: 0,
    description: "",
  });

  return (
    <form>
      <input name="name" value={formData.name} />
      <input name="price" value={formData.price} />
      <input name="description" value={formData.description} />
    </form>
  );
}
"""

REQUIRED_ARRAY_MESSAGE_MODEL = """\
import mongoose, { Schema } from "mongoose";

const schema = new Schema({
  code: { type: String, required: [true, "code is required"] },
});

export default mongoose.models.Coupon || mongoose.model("Coupon", schema);
"""

CODE_PLAN_TEMPLATE = {
    "files": [
        {"path": "models/Item.ts", "action": "create", "rationale": "r", "maps_to": ["Item"]},
        {"path": "app/item-listing-crud/page.tsx", "action": "create", "rationale": "r", "maps_to": []},
    ]
}


def _write(tmp_path, rel_path, content):
    file_path = tmp_path / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def test_flags_the_real_reported_bug_required_id_field_never_in_form(tmp_path):
    _write(tmp_path, "models/Item.ts", BUGGY_MODEL)
    _write(tmp_path, "app/item-listing-crud/page.tsx", BUGGY_FORM)

    results = check_required_field_form_coverage(tmp_path, CODE_PLAN_TEMPLATE)

    assert results == [{"field": "id", "model_file": "models/Item.ts", "status": "missing"}]


def test_passes_once_the_required_field_is_actually_removed_from_the_schema(tmp_path):
    fixed_model = BUGGY_MODEL.replace(
        '  id: { type: String, required: true, unique: true },\n', ""
    )
    _write(tmp_path, "models/Item.ts", fixed_model)
    _write(tmp_path, "app/item-listing-crud/page.tsx", FIXED_FORM)

    results = check_required_field_form_coverage(tmp_path, CODE_PLAN_TEMPLATE)

    assert results == []


def test_passes_when_the_required_field_is_present_as_a_name_attribute(tmp_path):
    model = """\
import mongoose, { Schema } from "mongoose";

const schema = new Schema({
  sku: { type: String, required: true },
});

export default mongoose.models.Item || mongoose.model("Item", schema);
"""
    form = """\
export default function Page() {
  return <form><input name="sku" /></form>;
}
"""
    _write(tmp_path, "models/Item.ts", model)
    _write(tmp_path, "app/item-listing-crud/page.tsx", form)

    results = check_required_field_form_coverage(tmp_path, CODE_PLAN_TEMPLATE)

    assert results == []


def test_auto_managed_fields_are_never_flagged_even_when_required(tmp_path):
    model = """\
import mongoose, { Schema } from "mongoose";

const schema = new Schema({
  createdAt: { type: Date, required: true, default: Date.now },
  updatedAt: { type: Date, required: true, default: Date.now },
  name: { type: String, required: true },
});

export default mongoose.models.Item || mongoose.model("Item", schema);
"""
    form = """\
export default function Page() {
  return <form><input name="name" /></form>;
}
"""
    _write(tmp_path, "models/Item.ts", model)
    _write(tmp_path, "app/item-listing-crud/page.tsx", form)

    results = check_required_field_form_coverage(tmp_path, CODE_PLAN_TEMPLATE)

    assert results == []


def test_required_array_with_custom_message_form_is_also_detected(tmp_path):
    _write(tmp_path, "models/Item.ts", REQUIRED_ARRAY_MESSAGE_MODEL)
    _write(tmp_path, "app/item-listing-crud/page.tsx", "export default function Page() { return null; }")

    plan = {
        "files": [
            {"path": "models/Item.ts", "action": "create", "rationale": "r", "maps_to": []},
            {"path": "app/item-listing-crud/page.tsx", "action": "create", "rationale": "r", "maps_to": []},
        ]
    }
    results = check_required_field_form_coverage(tmp_path, plan)

    assert results == [{"field": "code", "model_file": "models/Item.ts", "status": "missing"}]


def test_field_referenced_in_a_different_touched_frontend_file_still_counts(tmp_path):
    model = """\
import mongoose, { Schema } from "mongoose";

const schema = new Schema({
  category: { type: String, required: true },
});

export default mongoose.models.Item || mongoose.model("Item", schema);
"""
    form_component = """\
export default function ItemForm() {
  return <form><input name="category" /></form>;
}
"""
    plan = {
        "files": [
            {"path": "models/Item.ts", "action": "create", "rationale": "r", "maps_to": []},
            {"path": "app/item-listing-crud/page.tsx", "action": "create", "rationale": "r", "maps_to": []},
            {"path": "components/ItemForm.tsx", "action": "create", "rationale": "r", "maps_to": []},
        ]
    }
    _write(tmp_path, "models/Item.ts", model)
    _write(tmp_path, "app/item-listing-crud/page.tsx", "export default function Page() { return null; }")
    _write(tmp_path, "components/ItemForm.tsx", form_component)

    results = check_required_field_form_coverage(tmp_path, plan)

    assert results == []


def test_deleted_model_files_are_ignored(tmp_path):
    plan = {
        "files": [
            {"path": "models/Item.ts", "action": "delete", "rationale": "r", "maps_to": []},
            {"path": "app/item-listing-crud/page.tsx", "action": "create", "rationale": "r", "maps_to": []},
        ]
    }
    _write(tmp_path, "models/Item.ts", BUGGY_MODEL)
    _write(tmp_path, "app/item-listing-crud/page.tsx", BUGGY_FORM)

    results = check_required_field_form_coverage(tmp_path, plan)

    assert results == []


def test_no_model_files_in_plan_returns_empty(tmp_path):
    plan = {
        "files": [
            {"path": "app/item-listing-crud/page.tsx", "action": "create", "rationale": "r", "maps_to": []},
        ]
    }
    results = check_required_field_form_coverage(tmp_path, plan)
    assert results == []


def test_no_frontend_files_in_plan_returns_empty(tmp_path):
    plan = {
        "files": [
            {"path": "models/Item.ts", "action": "create", "rationale": "r", "maps_to": []},
        ]
    }
    _write(tmp_path, "models/Item.ts", BUGGY_MODEL)

    results = check_required_field_form_coverage(tmp_path, plan)
    assert results == []


def test_missing_files_on_disk_are_skipped_not_raised(tmp_path):
    # Plan references files that were never actually written -- should not crash.
    results = check_required_field_form_coverage(tmp_path, CODE_PLAN_TEMPLATE)
    assert results == []


def test_nested_brace_within_a_field_definition_is_a_known_limitation_not_a_crash(tmp_path):
    # A field whose own object literal contains a nested brace before `required: true` is not
    # detected (documented limitation, regex never crosses a brace boundary) -- confirms this
    # degrades safely (no false positive, no crash) rather than misattributing to another field.
    model = """\
import mongoose, { Schema } from "mongoose";

const schema = new Schema({
  email: {
    type: String,
    validate: { validator: (v) => v.includes("@"), message: "invalid" },
    required: true,
  },
});

export default mongoose.models.User || mongoose.model("User", schema);
"""
    plan = {
        "files": [
            {"path": "models/User.ts", "action": "create", "rationale": "r", "maps_to": []},
            {"path": "app/item-listing-crud/page.tsx", "action": "create", "rationale": "r", "maps_to": []},
        ]
    }
    _write(tmp_path, "models/User.ts", model)
    _write(tmp_path, "app/item-listing-crud/page.tsx", "export default function Page() { return null; }")

    results = check_required_field_form_coverage(tmp_path, plan)

    assert results == []
