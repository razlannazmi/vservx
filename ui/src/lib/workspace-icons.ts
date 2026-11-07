/** The icons an owner can give a workspace: animated Lucide icons from movingicons (@jis3r/icons). */

import type { Component } from "svelte";
import Activity from "@jis3r/icons/icons/activity";
import Blocks from "@jis3r/icons/icons/blocks";
import Bolt from "@jis3r/icons/icons/bolt";
import Bot from "@jis3r/icons/icons/bot";
import Boxes from "@jis3r/icons/icons/boxes";
import BrainCog from "@jis3r/icons/icons/brain-cog";
import ChartBar from "@jis3r/icons/icons/chart-bar";
import ChartLine from "@jis3r/icons/icons/chart-line";
import ChartScatter from "@jis3r/icons/icons/chart-scatter";
import CloudCog from "@jis3r/icons/icons/cloud-cog";
import Compass from "@jis3r/icons/icons/compass";
import Cpu from "@jis3r/icons/icons/cpu";
import Gauge from "@jis3r/icons/icons/gauge";
import Hammer from "@jis3r/icons/icons/hammer";
import Heart from "@jis3r/icons/icons/heart";
import InfinityIcon from "@jis3r/icons/icons/infinity";
import Key from "@jis3r/icons/icons/key";
import MessageSquareCode from "@jis3r/icons/icons/message-square-code";
import MonitorCog from "@jis3r/icons/icons/monitor-cog";
import Orbit from "@jis3r/icons/icons/orbit";
import Radar from "@jis3r/icons/icons/radar";
import Radio from "@jis3r/icons/icons/radio";
import Rocket from "@jis3r/icons/icons/rocket";
import ServerCog from "@jis3r/icons/icons/server-cog";
import ShieldCheck from "@jis3r/icons/icons/shield-check";
import Snowflake from "@jis3r/icons/icons/snowflake";
import Sparkles from "@jis3r/icons/icons/sparkles";
import Star from "@jis3r/icons/icons/star";
import Telescope from "@jis3r/icons/icons/telescope";
import Terminal from "@jis3r/icons/icons/terminal";
import WavesHorizontal from "@jis3r/icons/icons/waves-horizontal";
import Wifi from "@jis3r/icons/icons/wifi";

export type IconProps = { size?: number; color?: string; strokeWidth?: number; animate?: boolean; class?: string };

export type WorkspaceIconChoice = { name: string; label: string; component: Component<IconProps> };

/** What a workspace that hasn't chosen shows: a set of things, like a workspace's servers. */
export const DEFAULT_ICON = "boxes";

// Names are the package's file names, which is what the backend stores. Each is imported on its
// own, so only these are bundled. None of them is an icon the app already uses for something else
// (layers: the Workspaces heading; sun and moon: the mode toggle; a gear: settings), so a
// workspace's icon never reads as a control.
export const WORKSPACE_ICONS: WorkspaceIconChoice[] = [
  { name: "boxes", label: "Boxes", component: Boxes },
  { name: "server-cog", label: "Server", component: ServerCog },
  { name: "cpu", label: "Chip", component: Cpu },
  { name: "cloud-cog", label: "Cloud", component: CloudCog },
  { name: "monitor-cog", label: "Monitor", component: MonitorCog },
  { name: "terminal", label: "Terminal", component: Terminal },
  { name: "message-square-code", label: "Code", component: MessageSquareCode },
  { name: "bot", label: "Bot", component: Bot },
  { name: "brain-cog", label: "Brain", component: BrainCog },
  { name: "sparkles", label: "Sparkles", component: Sparkles },
  { name: "rocket", label: "Rocket", component: Rocket },
  { name: "telescope", label: "Telescope", component: Telescope },
  { name: "orbit", label: "Orbit", component: Orbit },
  { name: "radar", label: "Radar", component: Radar },
  { name: "gauge", label: "Gauge", component: Gauge },
  { name: "activity", label: "Activity", component: Activity },
  { name: "chart-line", label: "Line chart", component: ChartLine },
  { name: "chart-bar", label: "Bar chart", component: ChartBar },
  { name: "chart-scatter", label: "Scatter chart", component: ChartScatter },
  { name: "blocks", label: "Blocks", component: Blocks },
  { name: "bolt", label: "Bolt", component: Bolt },
  { name: "wifi", label: "Wi-Fi", component: Wifi },
  { name: "radio", label: "Radio", component: Radio },
  { name: "shield-check", label: "Shield", component: ShieldCheck },
  { name: "key", label: "Key", component: Key },
  { name: "hammer", label: "Hammer", component: Hammer },
  { name: "compass", label: "Compass", component: Compass },
  { name: "infinity", label: "Infinity", component: InfinityIcon },
  { name: "snowflake", label: "Snowflake", component: Snowflake },
  { name: "waves-horizontal", label: "Waves", component: WavesHorizontal },
  { name: "star", label: "Star", component: Star },
  { name: "heart", label: "Heart", component: Heart },
];

const BY_NAME = new Map(WORKSPACE_ICONS.map((icon) => [icon.name, icon]));

/** The name to show: the stored one if it's on the list, otherwise the default (the list may have changed). */
export function iconName(name: string | null | undefined): string {
  return name && BY_NAME.has(name) ? name : DEFAULT_ICON;
}

export function iconComponent(name: string | null | undefined): Component<IconProps> {
  return BY_NAME.get(iconName(name))!.component;
}
