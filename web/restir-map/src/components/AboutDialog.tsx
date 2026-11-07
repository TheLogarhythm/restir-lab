import { Modal } from "./Modal";

export function AboutDialog({ cutoffDate, onClose }: {
  cutoffDate: string;
  onClose: () => void;
}) {
  return (
    <Modal titleId="about-title" onClose={onClose}>
      <button
        className="dialog-close icon-button"
        aria-label="Close about dialog"
        onClick={onClose}
      >
        ×
      </button>
      <span className="eyebrow">ABOUT THE ATLAS</span>
      <h2 id="about-title">Follow the evidence.</h2>
      <p>
        ReSTIR Atlas
        maps documented connections between research papers. It covers published work directly related to ReSTIR and a few essential foundations, with preprints, abstracts, courses and implementation resources labeled separately.
      </p>
      <p>
        <strong>Arrows point from earlier work to later work.</strong>{" "}
        A solid line means the later paper explicitly adopts, extends or improves the earlier method. A dashed line means it cites the earlier paper. The All connections view merges the two into one edge where both apply, while keeping their evidence separate.
      </p>
      <p>
        Mainline, branch and optimization are editorial groupings, not quality rankings or a prescribed reading order. Papers can span several research areas. Only verified connections are shown; a missing edge does not establish that no connection exists.
      </p>
      <p>
        The default Method lineage view follows how methods develop. Switch to All connections to include verified citations. Select a paper and use its share button to copy a link. Your browser’s Back and Forward buttons restore previous selections.
      </p>
      <p>Node size shows distinct neighbors connected by verified method lineage, using all papers. Legend buttons highlight a group and open a reading entry if your current paper is outside that group. Select the same button again to remove the highlight and keep reading. Center fits the visible papers without moving nodes.</p>
      <p className="icon-credit">Prism Light by <a href="https://tabler.io/icons/icon/prism-light" target="_blank" rel="noreferrer">Tabler Icons</a> · <a href={`${import.meta.env.BASE_URL}licenses/tabler-icons-LICENSE.txt`} target="_blank" rel="noreferrer">MIT license</a></p>
      <div className="about-meta">
        Literature through {cutoffDate}
        <br />
        Keyboard: / to search · Tab to navigate · Enter to select · Esc to close dialogs
        <br />
        With the network focused: arrow keys to pan, + / − to zoom
      </div>
      <button className="primary-button" onClick={onClose}>
        Start exploring
      </button>
    </Modal>
  );
}
