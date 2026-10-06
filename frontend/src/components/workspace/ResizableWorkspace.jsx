import { Group, Panel, Separator, useDefaultLayout } from "react-resizable-panels";

// The Cursor-style 3-panel shell: left (tasks/features), middle (chat), right (output -- kept
// the largest of the three per direct user request). Sizes persist across reloads via
// useDefaultLayout's built-in localStorage persistence -- no custom state needed. Only mouse
// drag on the Separators resizes panels, matching the "adjust width using only the mouse" ask;
// no other resize affordance (buttons, keyboard shortcuts) is added on top of the library's own.
export default function ResizableWorkspace({ left, middle, right }) {
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    id: "autoforge-workspace",
    panelIds: ["left", "middle", "right"],
  });

  return (
    <Group
      orientation="horizontal"
      defaultLayout={defaultLayout}
      onLayoutChanged={onLayoutChanged}
      className="h-full"
    >
      <Panel id="left" minSize="15" defaultSize="20" maxSize="35" className="h-full">
        {left}
      </Panel>
      <ResizeHandle />
      <Panel id="middle" minSize="25" defaultSize="35" className="h-full">
        {middle}
      </Panel>
      <ResizeHandle />
      <Panel id="right" minSize="30" defaultSize="45" className="h-full">
        {right}
      </Panel>
    </Group>
  );
}

function ResizeHandle() {
  return (
    <Separator className="w-1.5 mx-1 flex-shrink-0 rounded-full bg-transparent hover:bg-accent-300 dark:hover:bg-accent-500/40 active:bg-accent-400 dark:active:bg-accent-500/60 transition-colors cursor-col-resize" />
  );
}
