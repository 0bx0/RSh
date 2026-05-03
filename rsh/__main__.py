import argparse
import sys

def cli() -> None:
    parser = argparse.ArgumentParser(prog='rsh', description='RSh - ROS2 Shell: interactive build/source/run REPL')
    parser.add_argument('-w', '--workspace', metavar='PATH', help='Colcon workspace to source and index on startup.')
    parser.add_argument('--log-level', default='WARNING', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Logging verbosity (default: WARNING).')
    args = parser.parse_args()
    from rsh.repl import main
    main(workspace=args.workspace, log_level=args.log_level)
if __name__ == '__main__':
    cli()