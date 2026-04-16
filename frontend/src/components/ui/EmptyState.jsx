import { cx } from '../../lib/classNames';

export default function EmptyState({ icon, title, description, compact = false }) {
  return (
    <div className={cx('empty-state', compact && 'empty-state-compact')}>
      <div className="empty-icon">{icon}</div>
      <div className="empty-title">{title}</div>
      {description ? <p className="empty-description">{description}</p> : null}
    </div>
  );
}
