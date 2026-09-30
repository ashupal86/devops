import { useState } from "react";

export function shareUrl(tag: string): string {
  return `${window.location.origin}/${tag}`;
}

export function ShareBox({ tag }: { tag: string }) {
  const [copied, setCopied] = useState(false);
  const url = shareUrl(tag);

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked; the URL is still visible to copy by hand */
    }
  }

  return (
    <div className="share">
      <code aria-label="Share link">{url}</code>
      <button type="button" className="secondary" onClick={copy}>
        {copied ? "Copied!" : "Copy link"}
      </button>
    </div>
  );
}
