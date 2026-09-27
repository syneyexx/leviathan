import { mediaControlCrops } from "../../assets/mediaControlAssets";
import { PlatformUnavailablePage } from "../../components/media/PlatformUnavailablePage";

export function InstagramPage() {
  return (
    <PlatformUnavailablePage
      platform="instagram"
      title="Instagram Control"
      heroImage={mediaControlCrops.instagramPoster}
      handle="@LeviathanOfficial"
    />
  );
}
