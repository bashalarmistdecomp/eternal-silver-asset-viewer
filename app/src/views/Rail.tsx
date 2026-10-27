import { Keyboard, Library as LibraryIcon, Wrench } from 'lucide-react'
import type { ReactNode } from 'react'
import icon from '../brand/asset-viewer-icon.png'
import type { Session } from '../lib/api'
import { groupTabs, tabIcon, type RailMode } from '../lib/tabs'
import { clickKeepsKeys, cn } from '../lib/utils'

/** The left rail: the library, then the open game's tabs, grouped as
 *  the mode lays them out (Fan or Advanced), and the ADV switch, lit while
 *  Advanced mode is on. */
export function Rail({
  mode,
  session,
  tab,
  railMode,
  onRailMode,
  onLibrary,
  onTab,
  onHelp,
}: {
  mode: 'library' | 'disc'
  session: Session | null
  tab: number
  railMode: RailMode
  onRailMode: (m: RailMode) => void
  onLibrary: () => void
  onTab: (index: number) => void
  onHelp: () => void
}) {
  const fan = railMode === 'fan'
  return (
    <nav className="w-14 border-r border-border bg-card flex flex-col shrink-0">
      <div className="h-11 border-b border-border flex items-center justify-center" title="Eternal Silver Asset Viewer">
        <img src={icon} alt="" width={32} height={32} draggable={false} className="select-none" />
      </div>
      <div className="flex-1 flex flex-col items-center py-1.5 gap-0.5 overflow-y-auto overflow-x-hidden">
        <RailButton title="Library — the games and their discs" active={mode === 'library'} onClick={onLibrary}>
          <LibraryIcon className="w-5 h-5" />
        </RailButton>
        {session &&
          groupTabs(session.tabs, railMode).map((g) => (
            <div key={g.label} className="flex flex-col items-center gap-0.5 w-full">
              <div className="w-8 border-t border-border mt-1 mb-px" />
              <RailLabel>{g.label}</RailLabel>
              {g.tabs.map((t) => {
                const Icon = tabIcon(t.key)
                return (
                  <RailButton
                    key={t.index}
                    title={t.name}
                    active={mode === 'disc' && tab === t.index}
                    onClick={() => onTab(t.index)}
                  >
                    <Icon className="w-[18px] h-[18px]" />
                  </RailButton>
                )
              })}
            </div>
          ))}
      </div>
      <div className="border-t border-border py-1.5 flex flex-col items-center gap-0.5">
        <button
          title={
            fan
              ? 'Advanced mode: off. The rail shows the game as a fan knows it.\nClick to turn it on: every tab, by kind of asset, each opening on its technical view.'
              : 'Advanced mode: on. Every tab, by kind of asset.\nClick to turn it off and see the game as a fan knows it.'
          }
          aria-pressed={!fan}
          onClick={() => onRailMode(fan ? 'advanced' : 'fan')}
          className={cn(
            'flex flex-col items-center justify-center w-10 h-10 rounded-md cursor-pointer transition-colors shrink-0',
            fan
              ? 'text-muted-foreground hover:bg-secondary hover:text-foreground'
              : 'bg-primary/15 text-primary ring-1 ring-inset ring-primary/60 hover:bg-primary/25',
          )}
        >
          <Wrench className="w-[18px] h-[18px]" />
          <span className="text-[9px] font-semibold uppercase tracking-wider leading-none mt-0.5">Adv</span>
        </button>
        <RailButton title="Keyboard and mouse (?)" onClick={onHelp}>
          <Keyboard className="w-5 h-5" />
        </RailButton>
      </div>
    </nav>
  )
}

function RailLabel({ children }: { children: ReactNode }) {
  return <span className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">{children}</span>
}

function RailButton({
  title,
  active,
  disabled,
  onClick,
  children,
}: {
  title: string
  active?: boolean
  disabled?: boolean
  onClick?: () => void
  children: ReactNode
}) {
  return (
    <button
      title={title}
      onMouseDown={clickKeepsKeys}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'relative flex items-center justify-center w-10 h-8 rounded-md transition-colors cursor-pointer disabled:opacity-35 disabled:cursor-default shrink-0',
        active
          ? 'bg-accent text-accent-foreground border-l-[3px] border-primary'
          : 'text-muted-foreground hover:bg-secondary hover:text-foreground disabled:hover:bg-transparent',
      )}
    >
      {children}
    </button>
  )
}
