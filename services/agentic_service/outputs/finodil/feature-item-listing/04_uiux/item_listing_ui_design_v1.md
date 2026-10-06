# UI/UX Design: Item Listing

> Review the attached page screenshots alongside this summary. The screenshots show the literal generated components -- there is no later regeneration step that could introduce drift from what you approve here.

---

## Page: Item Listing

- **Route:** `/items`
- **Actors:** logged-in users
- **Covers requirements:** FR-001, US-001, AC-001, AC-002, AC-003, AC-004, AC-005, AC-006
- **States:** idle, loading, error, success

### Components

- **ItemList** (new)
  - Covers UI expectations: A clean grid or table layout consistent with the rest of the app's existing styling, Responsive on both desktop and mobile widths
  - Why new: No existing component in the design system fits the specific needs of displaying a list of items with detailed information.
- **LoadingIndicator** (new)
  - Covers UI expectations: While items are loading, the page shows a loading indicator
  - Why new: No existing component in the design system fits the specific needs of displaying a loading indicator for item listing.
- **ErrorMessage** (new)
  - Covers UI expectations: If the fetch fails, it shows a clear error message instead of a blank page
  - Why new: No existing component in the design system fits the specific needs of displaying an error message for item listing.
- **EmptyState** (new)
  - Covers UI expectations: If there are no items, the page shows a clear empty state ('No items found')
  - Why new: No existing component in the design system fits the specific needs of displaying an empty state for item listing.

---

## Design System Impact

### New components introduced
- ItemList
- LoadingIndicator
- ErrorMessage
- EmptyState

### New design tokens introduced
- `color.primary`: #3B82F6 -- A new primary color is needed to differentiate the item listing feature from other parts of the app.
