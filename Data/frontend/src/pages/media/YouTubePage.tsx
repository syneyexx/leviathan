import { mediaControlCrops } from "../../assets/mediaControlAssets";
import { PlatformUnavailablePage } from "../../components/media/PlatformUnavailablePage";

export function YouTubePage() {
  return (
    <PlatformUnavailablePage
      platform="youtube"
      title="YouTube Control"
      heroImage={mediaControlCrops.youtubeHero}
      handle="@LeviathanOfficial"
    />
  );
}
