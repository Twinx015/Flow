from . import config


def _t():
    return config.Primary


def _m():
    return config.Tertiary


def _b():
    return config.Secondary


def _g():
    return config.Muted


def _r():
    return config.Reset


def _online_help():
    T, M, G, R = _t(), _m(), _g(), _r()
    return {
        "play": [
            f"{T}> play{R} {M}<query | index | liked>{R}",
            f"{G}  Search and play a song from YouTube.{R}",
            f"  {M}<query>{R}   {G}Search YouTube and play the top result{R}",
            f"  {M}<index>{R}   {G}Play a song by index from last search results{R}",
            f"  {M}liked{R}     {G}Play all liked songs{R}",
            f"  {M}Flags:{R} {G}{M}-bg{R} {G}background |{R} {M}-r{R} {G}repeat |{R} {M}-s{R} {G}shuffle |{R} {M}-d{R} {G}download{R}",
            f"  {G}Examples:{R}",
            f"    {G}play never gonna give you up{R}",
            f"    {G}play 3{R}",
            f"    {G}play liked{R} {M}-s{R}",
            f"    {G}play never gonna{R} {M}-d{R}",
        ],
        "search": [
            f"{T}> search{R} {M}<query>{R}",
            f"{G}  Search YouTube for tracks. Lists results with indices.{R}",
            f"{G}  Use the index with {M}'play <index>' {G}to play a specific result.{R}",
            f"  {G}Example:{R}",
            f"    {G}search daft punk{R}",
        ],
        "like": [
            f"{T}> like{R}",
            f"{G}  Like/unlike the currently playing song.{R}",
            f"{G}  Liked songs are saved to {M}~/.flow/library.json{R}",
            f"{G}  Use {M}'play liked'{G} to play all liked songs.{R}",
        ],
        "download": [
            f"{T}> download{R} {M}<query | index>{R} {M}[-f format]{R}",
            f"{G}  Download audio from YouTube without playing.{R}",
            f"  {M}<query>{R}   {G}Search and download the top result{R}",
            f"  {M}<index>{R}   {G}Download by index from last search results{R}",
            f"  {M}-f{R}        {G}Format: opus, m4a, mp3, webm (default from config){R}",
            f"{G}  Downloads are saved to {M}~/.flow/downloads/{R}",
            f"{G}  Already downloaded songs are skipped.{R}",
            f"  {G}Examples:{R}",
            f"    {G}download never gonna give you up{R}",
            f"    {G}download 2{R}",
            f"    {G}download never gonna{R} {M}-f mp3{R}",
        ],
        "delete": [
            f"{T}> delete{R} {M}<name | index>{R}",
            f"{G}  Delete a downloaded song from your library.{R}",
            f"  {M}<name>{R}   {G}Delete by song title{R}",
            f"  {M}<index>{R}   {G}Delete by index from last search results{R}",
            f"{G}  Asks for confirmation before deleting.{R}",
            f"  {G}Alias:{R} {M}dl-d{R}",
            f"  {G}Examples:{R}",
            f"    {G}delete never gonna give you up{R}",
            f"    {G}dl-d 2{R}",
        ],
        "savan": [
            f"{T}> savan{R} {M}<query | index>{R}",
            f"{G}  Search and play a song from JioSaavn.{R}",
            f"  {M}<query>{R}   {G}Search JioSaavn and play the top result{R}",
            f"  {M}<index>{R}   {G}Play song by index from last savan-s results{R}",
            f"  {M}Flags:{R} {G}{M}-bg{R} {G}background |{R} {M}-r{R} {G}repeat |{R} {M}-s{R} {G}shuffle{R}",
            f"  {G}Alias:{R} {M}svn{R}",
            f"  {G}Examples:{R}",
            f"    {G}savan hello{R}",
            f"    {G}savan 2{R}",
        ],
        "savan-s": [
            f"{T}> savan-s{R} {M}<query>{R}",
            f"{G}  Search JioSaavn for tracks. Lists results with indices.{R}",
            f"{G}  Use the index with {M}'savan <index>' {G}to play a specific result.{R}",
            f"  {G}Alias:{R} {M}svn-s{R}",
            f"  {G}Example:{R}",
            f"    {G}savan-s daft punk{R}",
        ],
        "radio": [
            f"{T}> radio{R} {M}<song_name> [index]{R}",
            f"{G}  Generate a radio mix based on a reference song.{R}",
            f"  {M}<song_name>{R}  {G}Search and play a radio mix from YouTube{R}",
            f"  {M}[index]{R}       {G}Play a specific track from the last radio list{R}",
            f"  {M}Flags:{R} {G}{M}-bg{R} {G}background |{R} {M}-d{R} {G}download{R}",
            f"{G}  Press Ctrl+C for next track, Ctrl+Q to quit. Alias:{R} {M}rd{R}",
            f"  {G}Examples:{R}",
            f"    {G}radio daft punk{R}",
            f"    {G}radio 5{R}",
        ],
        "switch": [
            f"{T}> switch{R}",
            f"{G}  Switch to Offline mode.{R}",
            f"{G}  Requires an active internet connection.{R}",
        ],
        "help": [
            f"{T}> help{R} {M}[-i]{R}",
            f"{G}  Show this help message.{R}",
            f"  {M}-i{R}     {G}Show detailed usage for all commands.{R}",
        ],
        "short": [
            f"{T}> short{R} {M}[index] [new_command]{R}",
            f"{G}  View or edit command shortcuts.{R}",
            f"{G}  With no arguments, list all shortcuts.{R}",
            f"  {M}<index>{R}          {G}Show shortcut at that index{R}",
            f"  {M}<index> <value>{R}  {G}Update shortcut at index to new command{R}",
            f"  {G}Examples:{R}",
            f"    {G}short{R}",
            f"    {G}short 3{R}",
            f"    {G}short 3 list{R}",
        ],
        "exit": [
            f"{T}> exit{R}",
            f"{G}  Exit Flow Music Player.{R}",
            f"{G}  Aliases:{R} {M}quit{R}, {M}q{R}",
        ],
        "config": [
            f"{T}> config{R} {M}<target> <value>{R}",
            f"{G}  Change settings. Use {M}config help{G} to see all targets.{R}",
            f"  {M}format{R}     {G}Default download format (opus, m4a, mp3, webm){R}",
            f"  {M}max_search{R} {G}Max YouTube search results (1-20, current: {M}{config.MAX_SEARCH_RESULTS}{G}){R}",
            f"  {M}max_radio{R}  {G}Max radio tracks (1-50, current: {M}{config.MAX_RESULTS_RADIO}{G}){R}",
        ],
        "check": [
            f"{T}> check{R}",
            f"{G}  Check all dependencies (ffmpeg, vlc, yt-dlp, psutil).{R}",
            f"{G}  Also available as: {M}flow --check{R}",
        ],
        "playlist": [
            f"{T}> playlist{R} {M}<subcommand> [args]{R}",
            f"{G}  Manage playlists. Subcommands:{R}",
            f"  {M}create{R} {G}<name>{R}          {G}Create a new playlist{R}",
            f"  {M}delete{R} {G}<name>{R}          {G}Delete a playlist{R}",
            f"  {M}add{R}    {G}<name> <index>{R}  {G}Add a song by search index{R}",
            f"  {M}remove{R} {G}<name> <index>{R}  {G}Remove a song by index{R}",
            f"  {M}list{R}   {G}<name>{R}          {G}List songs (with durations){R}",
            f"  {M}play{R}   {G}<name | liked>{R}  {G}Play all songs in a playlist{R}",
            f"  {M}rename{R} {G}<old> <new>{R}     {G}Rename a playlist{R}",
            f"  {M}move{R}   {G}<name> <from> <to>{R}  {G}Reorder one track (1-based){R}",
            f"  {M}duplicate{R} {G}<src> <new>{R}  {G}Copy a playlist{R}",
            f"  {M}merge{R}  {G}<dst> <src>{R}     {G}Merge src into dst (deduped){R}",
            f"  {M}sort{R}   {G}<name> [title|added|duration]{R}",
            f"  {M}clear{R} / {M}dedupe{R} / {M}info{R} {G}<name>{R}",
            f"  {M}export{R} {G}<name> [out.m3u]{R}  {G}Write an M3U file{R}",
            f"  {M}import{R} {G}<file.m3u> [name]{R}  {G}Import from M3U{R}",
            f"{G}  Names match fuzzily: case-insensitive, prefix/substring.{R}",
            f"{G}  'liked' plays your liked songs as a virtual playlist.{R}",
            f"  {M}Flags:{R} {G}{M}-bg{R} {G}background |{R} {M}-r{R} {G}repeat |{R} {M}-s{R} {G}shuffle{R}",
            f"  {G}Alias:{R} {M}plist{R}",
        ],
        "export": [
            f"{T}> export{R}",
            f"{G}  Backup ~/.flow config and data to ~/Downloads/flow_backup.zip{R}",
        ],
        "stop": [
            f"{T}> flow --stop{R}",
            f"{G}  Toggle stop/resume on the background VLC or web player.{R}",
            f"{G}  Use from shell: {M}flow --stop{R}",
        ],
    }


def _offline_help():
    T, B, G, R = _t(), _b(), _g(), _r()
    return {
        "play": [
            f"{T}> play{R} {B}<query | index | all | liked | album>{R}",
            f"{G}  Play a song from your local music library.{R}",
            f"  {B}<query>{R}   {G}Search and play matching song{R}",
            f"  {B}<index>{R}   {G}Play song by index from last search results{R}",
            f"  {B}all{R}       {G}Play all songs in the library{R}",
            f"  {B}liked{R}     {G}Play all liked songs{R}",
            f"  {B}<album>{R}   {G}Play all songs in a specific album{R}",
            f"  {B}Flags:{R} {G}{B}-bg{R} {G}background |{R} {B}-r{R} {G}repeat |{B}-s{R} {G}shuffle{R}",
            f"  {G}Examples:{R}",
            f"    {G}play never gonna{R}",
            f"    {G}play 2{R}",
            f"    {G}play all{R} {B}-s{R}",
            f"    {G}play liked{R}",
            f"    {G}play Greatest Hits{R}",
        ],
        "search": [
            f"{T}> search{R} {B}<query>{R}",
            f"{G}  Search your local music library for matching songs.{R}",
            f"{G}  Lists results with indices for use with {B}'play <index>'{R}",
            f"  {G}Example:{R}",
            f"    {G}search daft punk{R}",
        ],
        "list": [
            f"{T}> list{R}",
            f"{G}  List your entire music library.{R}",
            f"{G}  Shows Songs, Albums, and Liked Songs sections.{R}",
        ],
        "like": [
            f"{T}> like{R}",
            f"{G}  Like/unlike the currently playing song from offline mode.{R}",
            f"{G}  Liked songs are copied to {B}~/.flow/downloads/liked songs/{R}",
            f"{G}  Use {B}'play liked'{G} to play all liked songs.{R}",
        ],
        "radio": [
            f"{T}> radio{R}",
            f"{G}  Radio mode: shuffles and loops the entire local library.{R}",
            f"  {B}Ctrl+C{R}  {G}Skip to the next song{R}",
            f"  {B}Ctrl+Q{R}  {G}Exit radio mode{R}",
            f"  {B}Ctrl+P{R}  {G}Toggle pause{R}",
            f"  {B}Flags:{R} {G}{B}-bg{R} {G}background{R}",
            f"  {G}Alias:{R} {B}rd{R}",
        ],
        "playlist": [
            f"{T}> playlist{R} {B}<subcommand> [args]{R}",
            f"{G}  Manage playlists. Subcommands:{R}",
            f"  {B}create{R} {G}<name>{R}          {G}Create a new playlist{R}",
            f"  {B}delete{R} {G}<name>{R}          {G}Delete a playlist{R}",
            f"  {B}add{R}    {G}<name> <index|query>{R}  {G}Add from last search{R}",
            f"  {B}remove{R} {G}<name> <index>{R}  {G}Remove a song by index{R}",
            f"  {B}list{R}   {G}<name>{R}          {G}List songs (with durations){R}",
            f"  {B}play{R}   {G}<name | liked>{R}  {G}Play all songs in a playlist{R}",
            f"  {B}rename{R} {G}<old> <new>{R}     {G}Rename a playlist{R}",
            f"  {B}move{R}   {G}<name> <from> <to>{R}  {G}Reorder one track (1-based){R}",
            f"  {B}duplicate{R} {G}<src> <new>{R}  {G}Copy a playlist{R}",
            f"  {B}merge{R}  {G}<dst> <src>{R}     {G}Merge src into dst (deduped){R}",
            f"  {B}sort{R}   {G}<name> [title|added|duration]{R}",
            f"  {B}clear{R} / {B}dedupe{R} / {B}info{R} {G}<name>{R}",
            f"  {B}export{R} {G}<name> [out.m3u]{R}  {G}Write an M3U file{R}",
            f"  {B}import{R} {G}<file.m3u> [name]{R}  {G}Import from M3U{R}",
            f"  {B}download{R} {G}<name>{R}        {G}Download all tracks (-d works too){R}",
            f"{G}  Names match fuzzily: case-insensitive, prefix/substring.{R}",
            f"{G}  'liked' plays your liked songs as a virtual playlist.{R}",
            f"  {B}Flags:{R} {G}{B}-bg{R} {G}background |{R} {B}-r{R} {G}repeat |{B}-s{R} {G}shuffle{R}",
            f"  {G}Alias:{R} {B}plist{R}",
        ],
        "switch": [
            f"{T}> switch{R}",
            f"{G}  Switch to Online mode.{R}",
            f"{G}  Requires an active internet connection.{R}",
        ],
        "help": [
            f"{T}> help{R} {B}[-i]{R}",
            f"{G}  Show this help message.{R}",
            f"  {B}-i{R}     {G}Show detailed usage for all commands.{R}",
        ],
        "short": [
            f"{T}> short{R} {B}[index] [new_command]{R}",
            f"{G}  View or edit command shortcuts.{R}",
            f"{G}  With no arguments, list all shortcuts.{R}",
            f"  {B}<index>{R}          {G}Show shortcut at that index{R}",
            f"  {B}<index> <value>{R}  {G}Update shortcut at index to new command{R}",
            f"  {G}Examples:{R}",
            f"    {G}short{R}",
            f"    {G}short 3{R}",
            f"    {G}short 3 list{R}",
        ],
        "exit": [
            f"{T}> exit{R}",
            f"{G}  Exit Flow Music Player.{R}",
            f"{G}  Aliases:{R} {B}quit{R}, {B}q{R}",
        ],
        "config": [
            f"{T}> config{R} {B}<target> <value>{R}",
            f"{G}  Change settings. Use {B}config help{G} to see all targets.{R}",
            f"  {B}format{R}     {G}Default download format (opus, m4a, mp3, webm){R}",
            f"  {B}max_search{R} {G}Max YouTube search results (1-20, current: {B}{config.MAX_SEARCH_RESULTS}{G}){R}",
            f"  {B}max_radio{R}  {G}Max radio tracks (1-50, current: {B}{config.MAX_RESULTS_RADIO}{G}){R}",
        ],
        "check": [
            f"{T}> check{R}",
            f"{G}  Check all dependencies (ffmpeg, vlc, yt-dlp, psutil).{R}",
            f"{G}  Also available as: {B}flow --check{R}",
        ],
        "export": [
            f"{T}> export{R}",
            f"{G}  Backup ~/.flow config and data to ~/Downloads/flow_backup.zip{R}",
        ],
        "stop": [
            f"{T}> flow --stop{R}",
            f"{G}  Toggle stop/resume on the background VLC or web player.{R}",
            f"{G}  Use from shell: {B}flow --stop{R}",
        ],
    }


ONLINE_HELP = _online_help()
OFFLINE_HELP = _offline_help()
