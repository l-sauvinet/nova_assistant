import { describe, expect, it } from "vitest";
import { breadcrumbs, iconFor, typeLabel } from "./paths";
import { FileImage, Folder, File } from "lucide-react";

describe("breadcrumbs", () => {
  it("shows Windows drives mounted in WSL as drives", () => {
    expect(breadcrumbs("/mnt/c/Users/alice")).toEqual([
      { label: "Disque C:", path: "/mnt/c" },
      { label: "Users", path: "/mnt/c/Users" },
      { label: "alice", path: "/mnt/c/Users/alice" },
    ]);
  });

  it("splits Linux paths", () => {
    expect(breadcrumbs("/home/alice")).toEqual([
      { label: "Linux", path: "/" },
      { label: "home", path: "/home" },
      { label: "alice", path: "/home/alice" },
    ]);
    expect(breadcrumbs("/")).toEqual([{ label: "Linux", path: "/" }]);
  });

  it("splits Windows paths", () => {
    expect(breadcrumbs("C:\\Users\\alice\\Desktop")).toEqual([
      { label: "C:", path: "C:\\" },
      { label: "Users", path: "C:\\Users" },
      { label: "alice", path: "C:\\Users\\alice" },
      { label: "Desktop", path: "C:\\Users\\alice\\Desktop" },
    ]);
  });
});

describe("file types", () => {
  it("picks icons and French labels", () => {
    expect(iconFor({ is_dir: true, extension: "" })).toBe(Folder);
    expect(iconFor({ is_dir: false, extension: "png" })).toBe(FileImage);
    expect(iconFor({ is_dir: false, extension: "xyz" })).toBe(File);
    expect(typeLabel({ is_dir: false, extension: "docx" })).toBe("Document Word");
    expect(typeLabel({ is_dir: false, extension: "abc" })).toBe("Fichier ABC");
  });
});
