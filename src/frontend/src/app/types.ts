export type Screen = 'login' | 'sources' | 'discover' | 'route' | 'mapping' | 'run' | 'monitor'
export type Nav = (screen: Screen) => void
