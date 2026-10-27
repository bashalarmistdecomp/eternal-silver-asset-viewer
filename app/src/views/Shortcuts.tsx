import { Dialog } from '../components/ui/dialog'
import { keyName } from '../lib/utils'

const KEYS: [string, string][] = [
  ['↑ ↓  or  j k', 'Previous / next entry'],
  ['Enter  or  double-click', 'Select and play'],
  ['Space', 'Play / pause (the movie on stage, else the transport)'],
  ['/', 'Filter the list'],
  [keyName('Ctrl', 'F'), 'Find in the text shown (else filter the list)'],
  ['[  ]', 'Previous / next tab'],
  ['+  −', 'Zoom in / out (wheel works too, around the pointer)'],
  ['0  ·  1', 'Fit · actual size'],
  ['G', 'Toggle the 16 px grid'],
  ['I', 'Show / hide the Inspector'],
  ['Drag', 'Pan an image'],
  ['?', 'This list'],
]

export function Shortcuts({ onClose }: { onClose: () => void }) {
  return (
    <Dialog title="Keyboard and mouse" onClose={onClose} className="w-[460px]">
      <dl className="grid grid-cols-[150px_1fr] gap-x-4 gap-y-2 text-xs">
        {KEYS.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="font-mono text-primary">{k}</dt>
            <dd className="text-secondary-foreground">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="text-[11px] text-muted-foreground mt-4 border-t border-border pt-3">
        The transport plays on across tabs. Selecting another track loads it, after asking while one is playing; a map's ♪ plays the map's music.
      </p>
    </Dialog>
  )
}
