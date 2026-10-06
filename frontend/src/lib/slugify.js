// Mirrors app/utils/slugify.py exactly (lowercase, non-alphanumeric runs -> "-", trim "-") --
// used to compute a feature's own route path client-side (e.g. "Item Listing (CRUD)" ->
// "item-listing-crud") so Preview can open directly on that route instead of the generic
// multi-feature home page.
export function slugify(value) {
  return (
    (value || "")
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "untitled"
  );
}
