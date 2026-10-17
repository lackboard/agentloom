import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

export function SafeMarkdown({ children }: { children: string }) {
  return (
    <div className="prose-safe">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{children}</ReactMarkdown>
    </div>
  );
}
