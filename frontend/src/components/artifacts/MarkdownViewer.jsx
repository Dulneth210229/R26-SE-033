import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function MarkdownViewer({ content }) {
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none prose-table:text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}
