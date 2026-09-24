import type { TaskBoardColumn, TaskRecord } from "../../types/api";
import { TaskCard, type TaskCardAction } from "./TaskCard";
import { ColumnIcon, IconPlus } from "./TaskIcons";
import { COLUMN_META, COLUMN_ORDER, normalizeBoardColumn } from "./taskUtils";

type Props = {
  tasks: TaskRecord[];
  columnCounts?: Record<string, number>;
  selectedId: string | null;
  busy?: boolean;
  onSelect: (taskId: string) => void;
  onAction: (action: TaskCardAction, task: TaskRecord, boardColumn?: TaskBoardColumn) => void;
  onAddColumn: (column: TaskBoardColumn) => void;
};

export function TaskBoard({
  tasks,
  columnCounts,
  selectedId,
  busy,
  onSelect,
  onAction,
  onAddColumn,
}: Props) {
  return (
    <div className="lv-tasks-board">
      {COLUMN_ORDER.map((key) => {
        const meta = COLUMN_META[key];
        const cards = tasks.filter((t) => normalizeBoardColumn(t.boardColumn) === key);
        const count = columnCounts?.[key] ?? cards.length;
        return (
          <div key={key} className="lv-tasks-column">
            <div className="lv-tasks-column-head">
              <div className={`lv-tasks-column-title lv-tasks-column-title--${meta.tone}`}>
                <ColumnIcon type={meta.icon} />
                <span>
                  {meta.title} <span className="lv-tasks-column-count">({count})</span>
                </span>
              </div>
              <button
                type="button"
                className="lv-tasks-column-add"
                aria-label={`Add to ${meta.title}`}
                onClick={() => onAddColumn(key)}
              >
                <IconPlus />
              </button>
            </div>
            <div className="lv-tasks-column-body">
              {cards.length === 0 ? (
                <p className="lv-tasks-empty lv-tasks-empty--col">Geen taken</p>
              ) : (
                cards.map((card) => (
                  <TaskCard
                    key={card.taskId}
                    task={card}
                    selected={selectedId === card.taskId}
                    busy={busy}
                    onSelect={onSelect}
                    onAction={onAction}
                  />
                ))
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
