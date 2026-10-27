import { LoaderCircle, Music, Pause, Play } from 'lucide-react'
import { useState } from 'react'
import type { Result } from '../../lib/api'
import { useQuestion } from '../../lib/confirm'
import { songsOf, usePlaySong } from '../../lib/songs'
import { useTransport } from '../../lib/transport'
import { cn } from '../../lib/utils'

/** One button per song the result links to (a map's music, a fight's): it
 *  plays that song, or pauses and resumes it once it is the transport's. */
export function SongButtons({ result }: { result: Result }) {
  const play = usePlaySong()
  const t = useTransport()
  const [busy, setBusy] = useState<number | null>(null)
  // while the person is asked, the button waits without a spinner
  const asking = useQuestion() !== null
  const songs = songsOf(result)
  if (!play || !songs.length) return null
  return (
    <>
      {songs.map((song) => {
        const bgm = song.ref.id[0]
        const mine = !!t.loaded && t.loaded.program === result.program && !!t.loaded.clip.songs?.includes(bgm)
        const spin = busy === bgm && !asking
        const Icon = spin ? LoaderCircle : mine ? (t.playing ? Pause : Play) : Music
        const verb = mine ? (t.playing ? 'Pause' : 'Resume') : 'Play'
        return (
          <button
            key={bgm}
            title={`${verb} ${song.title}${song.note ? `: ${song.note}` : ''}`}
            disabled={busy !== null}
            onClick={() => {
              setBusy(bgm)
              void play(song.ref, song.title, result.disc).finally(() => setBusy(null))
            }}
            className={cn(
              'h-7 px-2 rounded flex items-center gap-1.5 text-[11px] cursor-pointer transition-colors shrink-0',
              mine ? 'bg-primary/20 text-primary' : 'text-stage-foreground/85 hover:bg-white/10 hover:text-white',
            )}
          >
            <Icon className={cn('w-3.5 h-3.5', spin && 'animate-spin')} />
            <span className="max-w-[180px] truncate">{song.title}</span>
          </button>
        )
      })}
    </>
  )
}
