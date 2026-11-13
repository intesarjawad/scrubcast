export function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  text = "",
  className = "",
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

const webProtocols = new Set(["http:", "https:"]);

// Hrefs can come from published data, so only web destinations are linkable.
export function isWebHref(href: string, base: string): boolean {
  try {
    return webProtocols.has(new URL(href, base).protocol);
  } catch {
    return false;
  }
}

export function link(text: string, href: string): HTMLAnchorElement {
  const node = element("a", text);
  if (isWebHref(href, window.location.href)) node.href = href;
  return node;
}
