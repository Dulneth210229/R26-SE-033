import PillDropdown from "../chat/PillDropdown";
import StatusBadge from "../common/StatusBadge";

// Replaces the plain native `<select>` version-picker (previously duplicated 3x in ResultTab.jsx
// with identical markup/className, rendering raw text like "v4 -- pending") with the same
// custom, rounded-popup styling PillDropdown already gives the composer's Agent/Model pickers --
// direct user request ("the artifact dropdown in each agent looks old"). Opens DOWNWARD
// (direction="down"): unlike the composer pickers, this one sits near the TOP of its panel, so
// an upward-opening menu would run off the panel edge.
export default function VersionSelect({ versions, selectedVersion, onChange }) {
  const options = versions.map((v) => ({
    value: v.version,
    label: (
      <span className="flex items-center gap-1.5">
        <span>v{v.version}</span>
        <StatusBadge status={v.approval_status} />
      </span>
    ),
  }));

  return (
    <PillDropdown
      value={selectedVersion}
      options={options}
      onChange={(newValue) => onChange(Number(newValue))}
      direction="down"
      title="Select a version"
      triggerClassName="max-w-none"
      scrollable={versions.length > 6}
    />
  );
}
