import { describe, expect, it } from "vitest";
import { isWebHref } from "../../src/dom";

const base = "https://example.org/scrub/";

describe("link destinations", () => {
  it.each(["https://ll2.thespacedevs.com/launch/1", "http://example.org/", "#how", "audit/"])(
    "accepts %s",
    (href) => {
      expect(isWebHref(href, base)).toBe(true);
    },
  );

  it.each(["javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<b>x</b>", "http://"])(
    "rejects %s",
    (href) => {
      expect(isWebHref(href, base)).toBe(false);
    },
  );
});
