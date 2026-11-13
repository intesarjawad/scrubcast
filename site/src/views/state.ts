import { element, link } from "../dom";
import type { SiteMessage } from "../messages";
import { routeHref } from "../router";

const destinations: Record<string, { href: string; label: string }> = {
  home_url: { href: routeHref(""), label: "the launch list" },
  audit_url: { href: routeHref("audit/"), label: "the audit" },
  calendar_url: { href: routeHref("data/calendar.ics"), label: "the launch calendar" },
  operations_url: { href: "#provenance", label: "Data and provenance" },
};

export function messageText(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => values[key] ?? "unavailable");
}

export function publicationState(
  message: SiteMessage,
  values: Record<string, string> = {},
): HTMLElement {
  const state = element("section", "", "notice");
  const title = element("h2", messageText(message.what, values));
  state.setAttribute("aria-label", title.textContent ?? "Launch data");
  if (message.what.startsWith("Loading")) state.setAttribute("role", "status");
  const next = element("p");
  for (const part of message.next.split(/(\{\w+_url\})/)) {
    const key = part.slice(1, -1);
    if (!/^\{\w+_url\}$/.test(part)) next.append(messageText(part, values));
    else if (key === "reload_url") next.append(link("reload launch data", window.location.href));
    else if (key === "launch_url" && values.launch_url)
      next.append(link("Launch Library 2 launch page", values.launch_url));
    else {
      const destination = destinations[key];
      if (!destination) throw new Error(`Unknown message destination: ${key}`);
      next.append(link(destination.label, destination.href));
    }
  }
  state.append(title, next);
  return state;
}
