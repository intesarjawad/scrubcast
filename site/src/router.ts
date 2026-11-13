export type Route =
  | { name: "home" }
  | { name: "next" }
  | { name: "launch"; id: string }
  | { name: "audit" }
  | { name: "notFound" };

export function isCardRoute(route: Route, search: string): boolean {
  return route.name === "launch" && new URLSearchParams(search).has("card");
}

export function basePath(base = import.meta.env.BASE_URL): string {
  const path = base.split("/").filter(Boolean).join("/");
  return path === "" ? "/" : `/${path}/`;
}

export function routeHref(path: string, base = import.meta.env.BASE_URL): string {
  return `${basePath(base)}${path.replace(/^\/+/, "")}`;
}

export function resolveRoute(pathname: string, base = import.meta.env.BASE_URL): Route {
  const prefix = basePath(base);
  if (!pathname.startsWith(prefix)) return { name: "notFound" };
  const path = pathname.slice(prefix.length);
  if (path === "") return { name: "home" };
  if (path === "next/") return { name: "next" };
  if (path === "audit/") return { name: "audit" };
  const match = /^launch\/([^/]+)\/$/.exec(path);
  const encodedId = match?.[1];
  if (encodedId === undefined) return { name: "notFound" };
  try {
    const id = decodeURIComponent(encodedId);
    return id.includes("/") || id.trim() === "" ? { name: "notFound" } : { name: "launch", id };
  } catch {
    return { name: "notFound" };
  }
}
