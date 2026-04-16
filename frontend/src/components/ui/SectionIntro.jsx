export default function SectionIntro({ eyebrow, title, description, aside }) {
  return (
    <div className="section-intro">
      <div>
        {eyebrow ? <div className="section-eyebrow">{eyebrow}</div> : null}
        <h1 className="section-title">{title}</h1>
        {description ? <p className="section-description">{description}</p> : null}
      </div>
      {aside ? <div className="section-aside">{aside}</div> : null}
    </div>
  );
}
