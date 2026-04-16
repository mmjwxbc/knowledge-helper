import { cx } from '../../lib/classNames';

export default function StatusPill({ children, tone = 'neutral' }) {
  return <span className={cx('status-pill', `status-pill-${tone}`)}>{children}</span>;
}
