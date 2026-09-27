import { mediaControlCrops } from "../../assets/mediaControlAssets";
import { PlatformUnavailablePage } from "../../components/media/PlatformUnavailablePage";

export function FacebookPage() {
  return (
    <PlatformUnavailablePage
      platform="facebook"
      title="Facebook Control"
      heroImage={mediaControlCrops.facebookHero}
      handle="@LeviathanOfficial"
    />
  );
}
