"use client";

import { FbIcon } from "../../icons";

/** Pull requests — NOT APPLICABLE: HADES has no GitHub PR Coding API. */
export function CodingTabPullRequests() {
  return (
    <div className="coding-pr-tab">
      <article className="coding-panel coding-unavailable-panel">
        <div className="coding-panel-head">
          <strong>Pull requests</strong>
          <FbIcon name="link" size={14} />
        </div>
        <div className="coding-unavailable">
          <h3>PR-integratie niet beschikbaar</h3>
          <p>
            HADES Coding ondersteunt momenteel geen GitHub/GitLab pull-request workflows via de Coding API.
            Er zijn geen endpoints voor PR list/create/review/checks.
          </p>
          <p>
            Gebruik lokale Git-status en commit onder <strong>Branches</strong>, of een externe Git-client voor PRs.
            Geen nep-PR-rijen worden getoond.
          </p>
        </div>
      </article>
    </div>
  );
}
