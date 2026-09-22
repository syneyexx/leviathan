import { PixelMockPage } from "./PixelMockPage";

/** Pixel-exact Evidence Vault content from design reference. */
export function EvidenceVaultPage() {
  return (
    <PixelMockPage
      pageKey="evidence"
      title="Evidence Vault"
      modeLabel="Evidence Mode"
      searchPlaceholder="Search evidence, sources, content, hash, or tags..."
      systemItems={["SYSTEMS OPERATIONAL", "LLM", "NEURAL", "MEMORY", "TOOLS"]}
    />
  );
}
