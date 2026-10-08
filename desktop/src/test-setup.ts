import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Recent Chrome returns a Promise from scrollIntoView; mirror it so effects returning it fail in tests too.
Element.prototype.scrollIntoView = (() => Promise.resolve()) as unknown as Element["scrollIntoView"];

afterEach(cleanup);

URL.createObjectURL = () => "blob:preview";
