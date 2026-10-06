// Canned revision-comment starters shown per stage, purely client-side -- clicking one just
// populates the comment box, it does not call any new backend capability. Directly answers the
// reference dashboard's quick-action buttons ("Suggest FRs based on this", "Clarify HIPAA reqs").
export const SUGGESTION_CHIPS = {
  requirement: [
    "Suggest additional functional requirements based on this",
    "Clarify edge cases and error scenarios",
    "Add non-functional requirements for performance and security",
  ],
  domain: [
    "Double-check this against domain best practices",
    "Are there any compliance requirements I'm missing?",
  ],
  architecture: [
    "Simplify this to fewer endpoints",
    "Add a caching layer for read-heavy endpoints",
    "Reconsider the data model for scalability",
  ],
  uiux: [
    "Make the layout more mobile-friendly",
    "Add loading and empty states",
  ],
  coder: [
    "Add input validation on all endpoints",
    "Improve error messages returned to the client",
    "Add a loading spinner while data is being fetched",
  ],
};
