import { mediaControlCrops } from "../../assets/mediaControlAssets";
import { PlatformUnavailablePage } from "../../components/media/PlatformUnavailablePage";

export function TikTokPage() {
  return (
    <PlatformUnavailablePage
      platform="tiktok"
      title="TikTok Control"
      heroImage={mediaControlCrops.tiktokPoster}
      handle="@LeviathanOfficial"
    />
  );
}
