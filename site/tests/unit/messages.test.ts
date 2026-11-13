import { describe, expect, it } from "vitest";
import { messages } from "../../src/messages";

describe("actionable site messages", () => {
  it.each(Object.entries(messages))(
    "%s explains the state and links to a next step",
    (_name, message) => {
      expect(message.what.trim()).not.toBe("");
      expect(message.next.trim()).not.toBe("");
      expect(message.next).toMatch(/\{\w+_url\}/);
    },
  );
});
