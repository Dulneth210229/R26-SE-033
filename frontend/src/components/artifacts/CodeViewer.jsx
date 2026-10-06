import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";

export default function CodeViewer({ content, language = "jsx" }) {
  return (
    <SyntaxHighlighter language={language} style={vscDarkPlus} showLineNumbers customStyle={{ borderRadius: 6 }}>
      {content}
    </SyntaxHighlighter>
  );
}
