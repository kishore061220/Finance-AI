/**
 * @format
 */

import { AppRegistry } from 'react-native';
import App from './App';
import { name as appName } from './app.json';
import { pushService } from './src/services/push';

// Register the background message handler before the root component so a
// notification that launched the app from a terminated state still runs it.
pushService.registerBackgroundHandler();

AppRegistry.registerComponent(appName, () => App);
