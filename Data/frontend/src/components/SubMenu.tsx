import { NavLink, useLocation, useSearchParams } from "react-router-dom";
import {
  findMainMenuByPath,
  findSubMenuItem,
  submenuHref,
  type MainMenuItem,
} from "../navigation/menu";

type SubMenuProps = {
  /** Override section detection (rarely needed). */
  section?: MainMenuItem;
};

/**
 * SUBMENU — contextual tabs under the middle content area.
 * Items with a dedicated page navigate; others stay on the section route with ?tab=.
 */
export function SubMenu({ section: sectionProp }: SubMenuProps) {
  const location = useLocation();
  const [params] = useSearchParams();
  const section = sectionProp ?? findMainMenuByPath(location.pathname);
  const active = findSubMenuItem(section, location.pathname, params.get("tab"));

  return (
    <nav className="lv-submenu" aria-label={`${section.label} submenu`}>
      <div className="lv-tabs lv-submenu-tabs" role="tablist">
        {section.submenu.map((item) => {
          const href = submenuHref(section, item);
          const isActive = active?.id === item.id;
          return (
            <NavLink
              key={item.id}
              to={href}
              end
              role="tab"
              aria-selected={isActive}
              className={() => `lv-tab${isActive ? " is-active" : ""}`}
              style={{ textDecoration: "none" }}
            >
              {isActive ? <span className="lv-tab-dot" /> : null}
              {item.label}
            </NavLink>
          );
        })}
      </div>
    </nav>
  );
}
